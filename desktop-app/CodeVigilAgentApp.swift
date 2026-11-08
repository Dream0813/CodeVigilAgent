import Cocoa

private enum AgentTask {
    case chat(String)
    case review
}

private final class ProcessOutput {
    private let lock = NSLock()
    private var stdout = Data()
    private var stderr = Data()

    func append(_ data: Data, isError: Bool) {
        lock.lock()
        if isError { stderr.append(data) } else { stdout.append(data) }
        lock.unlock()
    }

    func values() -> (Data, Data) {
        lock.lock()
        defer { lock.unlock() }
        return (stdout, stderr)
    }
}

final class CodeVigilAgentDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSWindow!
    private let repositoryField = NSTextField()
    private let promptField = NSTextField()
    private let outputView = NSTextView()
    private let statusLabel = NSTextField(labelWithString: "就绪")
    private var sendButton: NSButton!
    private var cancelButton: NSButton!
    private var newConversationButton: NSButton!
    private var clearDisplayButton: NSButton!
    private var actionButtons: [NSButton] = []
    private var runningProcess: Process?
    private var runningPipes: [Pipe] = []
    private var runningReaders: DispatchGroup?
    private var activeTaskID: UUID?
    private var cancelRequested = false
    private var sessionID = UUID().uuidString
    private var sessionRepository = ""

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildWindow()
        repositoryField.stringValue = UserDefaults.standard.string(forKey: "lastRepositoryPath") ?? ""
        sessionRepository = repositoryField.stringValue
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopProcessForTermination()
    }

    func windowWillClose(_ notification: Notification) {
        stopProcessForTermination()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    private func buildWindow() {
        let content = NSView()
        content.translatesAutoresizingMaskIntoConstraints = false
        content.wantsLayer = true
        content.layer?.backgroundColor = NSColor(calibratedWhite: 0.07, alpha: 1).cgColor

        let title = NSTextField(labelWithString: "CodeVigil Agent")
        title.font = .systemFont(ofSize: 25, weight: .semibold)
        title.textColor = NSColor(calibratedRed: 0.48, green: 0.92, blue: 0.78, alpha: 1)

        let subtitle = NSTextField(labelWithString: "昇腾 AI Infra 代码审查与问题诊断")
        subtitle.font = .systemFont(ofSize: 13)
        subtitle.textColor = NSColor(calibratedWhite: 0.62, alpha: 1)

        statusLabel.font = .systemFont(ofSize: 12, weight: .medium)
        statusLabel.textColor = NSColor(calibratedWhite: 0.72, alpha: 1)
        statusLabel.alignment = .right

        let header = NSStackView(views: [title, subtitle, statusLabel])
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = 12
        header.setCustomSpacing(18, after: subtitle)
        title.setContentHuggingPriority(.required, for: .horizontal)
        subtitle.setContentHuggingPriority(.required, for: .horizontal)
        statusLabel.setContentHuggingPriority(.required, for: .horizontal)

        repositoryField.placeholderString = "选择要审查的 Git 仓库目录"
        repositoryField.font = .systemFont(ofSize: 13)
        repositoryField.textColor = NSColor(calibratedWhite: 0.9, alpha: 1)
        repositoryField.backgroundColor = NSColor(calibratedWhite: 0.12, alpha: 1)
        repositoryField.isBezeled = true
        repositoryField.bezelStyle = .roundedBezel
        repositoryField.translatesAutoresizingMaskIntoConstraints = false

        let chooseButton = makeButton("选择目录", action: #selector(chooseRepository))
        let repoLabel = NSTextField(labelWithString: "仓库")
        repoLabel.font = .systemFont(ofSize: 13, weight: .medium)
        repoLabel.textColor = NSColor(calibratedWhite: 0.78, alpha: 1)
        repoLabel.setContentHuggingPriority(.required, for: .horizontal)

        let repoRow = NSStackView(views: [repoLabel, repositoryField, chooseButton])
        repoRow.orientation = .horizontal
        repoRow.alignment = .centerY
        repoRow.spacing = 10
        repositoryField.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        let reviewButton = makeButton("审查当前改动", action: #selector(reviewChanges))
        let offlineButton = makeButton("离线审查", action: #selector(offlineReview))
        let settingsButton = makeButton("模型设置", action: #selector(configureModel))
        let actionRow = NSStackView(views: [reviewButton, offlineButton, settingsButton])
        actionRow.orientation = .horizontal
        actionRow.alignment = .centerY
        actionRow.spacing = 10
        actionButtons = [reviewButton, offlineButton, settingsButton]

        outputView.isEditable = false
        outputView.isSelectable = true
        outputView.font = .systemFont(ofSize: 14)
        outputView.textColor = NSColor(calibratedWhite: 0.95, alpha: 1)
        outputView.backgroundColor = NSColor(calibratedWhite: 0.035, alpha: 1)
        outputView.textContainerInset = NSSize(width: 16, height: 16)
        outputView.string = "欢迎使用 CodeVigil Agent。\n选择 Git 仓库以审查改动；使用 AI 前请在模型设置中填写 API 信息。\n\n"

        let scrollView = NSScrollView()
        scrollView.documentView = outputView
        scrollView.hasVerticalScroller = true
        scrollView.borderType = .bezelBorder
        scrollView.translatesAutoresizingMaskIntoConstraints = false

        promptField.placeholderString = "输入问题，例如：分析这个仓库最近的改动"
        promptField.font = .systemFont(ofSize: 13)
        promptField.textColor = NSColor(calibratedWhite: 0.9, alpha: 1)
        promptField.backgroundColor = NSColor(calibratedWhite: 0.12, alpha: 1)
        promptField.isBezeled = true
        promptField.bezelStyle = .roundedBezel
        promptField.target = self
        promptField.action = #selector(sendPrompt)
        promptField.translatesAutoresizingMaskIntoConstraints = false

        sendButton = makeButton("发送", action: #selector(sendPrompt))
        cancelButton = makeButton("取消", action: #selector(cancelTask))
        cancelButton.isHidden = true
        newConversationButton = makeButton("新对话", action: #selector(newConversation))
        clearDisplayButton = makeButton("清空显示", action: #selector(clearDisplay))
        newConversationButton.toolTip = "开始新的会话并清空当前显示；旧会话文件会保留"
        clearDisplayButton.toolTip = "只清空屏幕上的消息，不会清除当前会话上下文"
        let chatRow = NSStackView(views: [promptField, sendButton, cancelButton,
                                          newConversationButton, clearDisplayButton])
        chatRow.orientation = .horizontal
        chatRow.alignment = .centerY
        chatRow.spacing = 10
        promptField.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        let stack = NSStackView(views: [header, repoRow, actionRow, scrollView, chatRow])
        stack.orientation = .vertical
        stack.alignment = .width
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false

        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 22),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -22),
            stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 20),
            stack.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -20),
            scrollView.heightAnchor.constraint(greaterThanOrEqualToConstant: 320),
            repositoryField.heightAnchor.constraint(equalToConstant: 30),
            promptField.heightAnchor.constraint(equalToConstant: 30),
        ])

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1080, height: 720),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "CodeVigil Agent"
        window.minSize = NSSize(width: 760, height: 520)
        window.center()
        window.contentView = content
        window.appearance = NSAppearance(named: .darkAqua)
        window.delegate = self
    }

    private func makeButton(_ title: String, action: Selector) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.bezelStyle = .rounded
        button.font = .systemFont(ofSize: 13, weight: .medium)
        button.contentTintColor = NSColor(calibratedRed: 0.48, green: 0.92, blue: 0.78, alpha: 1)
        return button
    }

    @objc private func chooseRepository() {
        let panel = NSOpenPanel()
        panel.title = "选择 Git 仓库"
        panel.prompt = "选择"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            self?.repositoryField.stringValue = url.path
            UserDefaults.standard.set(url.path, forKey: "lastRepositoryPath")
            self?.setStatus("已选择仓库")
        }
    }

    @objc private func reviewChanges() {
        runReview(offline: false)
    }

    @objc private func offlineReview() {
        runReview(offline: true)
    }

    @objc private func configureModel() {
        let configRoot = ProcessInfo.processInfo.environment["REVIEWAGENT_HOME"] ??
            URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent(".reviewagent").path
        let configURL = URL(fileURLWithPath: configRoot).appendingPathComponent("ai_config.json")
        let existing = (try? Data(contentsOf: configURL)).flatMap {
            (try? JSONSerialization.jsonObject(with: $0)) as? [String: Any]
        } ?? [:]
        let provider = NSPopUpButton()
        provider.addItems(withTitles: ["deepseek", "openai", "claude", "glm"])
        provider.selectItem(withTitle: existing["provider"] as? String ?? "deepseek")
        let model = NSTextField(string: existing["model"] as? String ?? "deepseek-chat")
        let baseURL = NSTextField(string: existing["base_url"] as? String ?? "")
        baseURL.placeholderString = "默认地址（可留空）"
        let key = NSSecureTextField(string: "")
        key.placeholderString = "留空以保留现有密钥"
        let grid = NSGridView(views: [
            [NSTextField(labelWithString: "服务商"), provider],
            [NSTextField(labelWithString: "模型 ID"), model],
            [NSTextField(labelWithString: "API 地址"), baseURL],
            [NSTextField(labelWithString: "API Key"), key],
        ])
        grid.columnSpacing = 12
        grid.rowSpacing = 10
        grid.frame = NSRect(x: 0, y: 0, width: 420, height: 150)
        [model, baseURL, key].forEach { $0.widthAnchor.constraint(equalToConstant: 300).isActive = true }
        let alert = NSAlert()
        alert.messageText = "模型设置"
        alert.informativeText = "API Key 保存在本机 \(configURL.path)。"
        alert.accessoryView = grid
        alert.addButton(withTitle: "保存")
        alert.addButton(withTitle: "取消")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        guard !model.stringValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            appendOutput("\n模型 ID 不能为空。\n")
            return
        }
        var config = existing
        let selectedProvider = provider.titleOfSelectedItem ?? "deepseek"
        config["provider"] = selectedProvider
        config["model"] = model.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        config["base_url"] = baseURL.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if !key.stringValue.isEmpty {
            config["api_key"] = key.stringValue
        } else if selectedProvider != (existing["provider"] as? String ?? "deepseek") {
            config["api_key"] = ""
        }
        do {
            try FileManager.default.createDirectory(at: configURL.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            let data = try JSONSerialization.data(withJSONObject: config, options: [.prettyPrinted, .sortedKeys])
            try data.write(to: configURL, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: configURL.path)
            setStatus("设置已保存")
        } catch {
            appendOutput("\n保存模型设置失败：\(error.localizedDescription)\n")
            setStatus("设置失败")
        }
    }

    @objc private func sendPrompt() {
        let prompt = promptField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty else { return }
        promptField.stringValue = ""
        let repository = repositoryField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if repository != sessionRepository {
            sessionID = UUID().uuidString
            sessionRepository = repository
            outputView.string = ""
            appendOutput("已切换仓库，开始新的对话会话。\n\n", color: .secondaryLabelColor)
        }
        runAgent(arguments: ["chat", "--message", prompt, "--network", "auto",
                             "--session", "desktop-\(sessionID)", "--json"],
                 task: .chat(prompt))
    }

    @objc private func newConversation() {
        guard runningProcess == nil else { return }
        sessionID = UUID().uuidString
        outputView.string = ""
        appendOutput("已开始新对话。旧会话仍保留在本机。\n\n", color: .secondaryLabelColor)
        setStatus("新对话")
    }

    @objc private func clearDisplay() {
        let alert = NSAlert()
        alert.messageText = "清空消息显示？"
        alert.informativeText = "只清空屏幕内容；当前会话上下文仍会用于后续提问。选择“新对话”才会开始空白会话。"
        alert.addButton(withTitle: "清空显示")
        alert.addButton(withTitle: "取消")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        outputView.string = ""
        setStatus("显示已清空；会话保留")
    }

    @objc private func cancelTask() {
        guard let process = runningProcess else { return }
        cancelRequested = true
        cancelButton.isEnabled = false
        setStatus("正在取消…")
        terminate(process)
    }

    private func runReview(offline: Bool) {
        let repoPath = repositoryField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !repoPath.isEmpty else {
            appendOutput("\n请选择一个 Git 仓库目录后再审查。\n", color: .systemRed)
            setStatus("缺少仓库目录")
            return
        }
        let repo = URL(fileURLWithPath: repoPath).standardizedFileURL
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: repo.path, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            appendOutput("\n审查失败：目录不存在或不是文件夹：\(repo.path)\n", color: .systemRed)
            setStatus("仓库目录无效")
            return
        }
        let git = Process()
        git.executableURL = URL(fileURLWithPath: "/usr/bin/git")
        git.arguments = ["-C", repo.path, "rev-parse", "--show-toplevel"]
        git.standardOutput = FileHandle.nullDevice
        git.standardError = FileHandle.nullDevice
        do {
            try git.run()
            git.waitUntilExit()
        } catch {
            appendOutput("\n审查失败：无法启动 Git：\(error.localizedDescription)\n", color: .systemRed)
            setStatus("Git 不可用")
            return
        }
        guard git.terminationStatus == 0 else {
            appendOutput("\n审查失败：所选目录不是有效的 Git 仓库。\n", color: .systemRed)
            setStatus("不是 Git 仓库")
            return
        }
        UserDefaults.standard.set(repo.path, forKey: "lastRepositoryPath")
        var arguments = ["review"]
        if offline { arguments.append("--offline") }
        arguments.append("--json")
        runAgent(arguments: arguments, task: .review)
    }

    private func runAgent(arguments: [String], task: AgentTask) {
        guard runningProcess == nil else {
            setStatus("任务正在运行")
            return
        }

        let repo = repositoryField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        let workingDirectory = repo.isEmpty ? backendRoot() : URL(fileURLWithPath: repo)
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: workingDirectory.path, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            appendOutput("\n找不到工作目录：\(workingDirectory.path)\n", color: .systemRed)
            setStatus("目录不存在")
            return
        }

        let pythonCandidates = [
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "\(NSHomeDirectory())/.local/bin/python3",
            "/usr/bin/python3",
        ]
        guard let pythonPath = pythonCandidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            appendOutput("\n找不到 Python 3。请先安装 Python 3.7+。\n", color: .systemRed)
            setStatus("缺少 Python")
            return
        }

        let process = Process()
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        let output = ProcessOutput()
        let readers = DispatchGroup()
        let taskID = UUID()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        let cliPath = backendRoot().appendingPathComponent("ascend_cli.py").path
        process.arguments = ["-c", """
            import os, signal, subprocess, sys
            child = subprocess.Popen([sys.executable] + sys.argv[1:], start_new_session=True)
            def stop(signum, _frame):
                if child.poll() is None:
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                        child.wait(timeout=1)
                    except (ProcessLookupError, ChildProcessError):
                        pass
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                raise SystemExit(128 + signum)
            signal.signal(signal.SIGTERM, stop)
            sys.exit(child.wait())
            """, cliPath] + arguments
        process.currentDirectoryURL = workingDirectory
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = backendRoot().path + ":" + (environment["PYTHONPATH"] ?? "")
        environment["REVIEWAGENT_HOME"] = environment["REVIEWAGENT_HOME"] ??
            URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent(".reviewagent").path
        process.environment = environment

        switch task {
        case .chat(let prompt):
            appendOutput("你\n", color: NSColor(calibratedRed: 0.48, green: 0.92, blue: 0.78, alpha: 1), bold: true)
            appendOutput(prompt + "\n\n")
        case .review:
            appendOutput(offlineReviewHeading(arguments) + "\n", color: NSColor(calibratedRed: 0.48, green: 0.92, blue: 0.78, alpha: 1), bold: true)
        }
        setStatus("运行中…")
        runningProcess = process
        runningPipes = [stdoutPipe, stderrPipe]
        runningReaders = readers
        activeTaskID = taskID
        cancelRequested = false
        setControlsRunning(true)
        readers.enter()
        stdoutPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                readers.leave()
            }
            else { output.append(data, isError: false) }
        }
        readers.enter()
        stderrPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                readers.leave()
            }
            else { output.append(data, isError: true) }
        }
        process.terminationHandler = { [weak self] terminatedProcess in
            guard let self else { return }
            DispatchQueue.global().async {
                readers.wait()
                DispatchQueue.main.async {
                    guard self.activeTaskID == taskID else { return }
                    let (stdout, stderr) = output.values()
                    try? stdoutPipe.fileHandleForReading.close()
                    try? stderrPipe.fileHandleForReading.close()
                    self.runningProcess = nil
                    self.runningPipes = []
                    self.runningReaders = nil
                    self.activeTaskID = nil
                    self.setControlsRunning(false)
                    if self.cancelRequested {
                        self.appendOutput("\n任务已取消。\n", color: .systemOrange)
                        self.setStatus("已取消")
                    } else {
                        self.finishTask(task, status: terminatedProcess.terminationStatus,
                                        stdout: stdout, stderr: stderr)
                    }
                }
            }
        }

        do {
            try process.run()
        } catch {
            runningProcess = nil
            [stdoutPipe, stderrPipe].forEach { pipe in
                pipe.fileHandleForReading.readabilityHandler = nil
                try? pipe.fileHandleForReading.close()
            }
            runningPipes = []
            runningReaders = nil
            activeTaskID = nil
            setControlsRunning(false)
            appendOutput("\n启动失败：\(error.localizedDescription)\n", color: .systemRed)
            setStatus("启动失败")
        }
    }

    private func backendRoot() -> URL {
        Bundle.main.resourceURL?.appendingPathComponent("backend") ??
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
    }

    private func finishTask(_ task: AgentTask, status: Int32, stdout: Data, stderr: Data) {
        switch task {
        case .chat:
            guard let payload = try? JSONSerialization.jsonObject(with: stdout) as? [String: Any] else {
                appendOutput("请求失败：CLI 返回无效 JSON。\n\(safeDiagnostic(stderr))\n", color: .systemRed)
                setStatus("请求失败")
                return
            }
            guard status == 0, payload["ok"] as? Bool == true else {
                appendOutput("Agent 请求失败：\(payload["error"] as? String ?? "CLI 以退出码 \(status) 结束。")\n",
                             color: .systemRed)
                setStatus("请求失败")
                return
            }
            guard let reply = payload["reply"] as? String else {
                appendOutput("请求失败：JSON 响应缺少 Agent 回复。\n", color: .systemRed)
                setStatus("请求失败")
                return
            }
            appendOutput("Agent\n", color: NSColor(calibratedRed: 0.48, green: 0.92, blue: 0.78, alpha: 1), bold: true)
            appendOutput(reply + "\n\n")
            setStatus("完成")
        case .review:
            renderReview(status: status, stdout: stdout, stderr: stderr)
        }
    }

    private func renderReview(status: Int32, stdout: Data, stderr: Data) {
        guard let payload = try? JSONSerialization.jsonObject(with: stdout) as? [String: Any] else {
            appendOutput("审查失败：CLI 返回无效 JSON；结果未作为通过处理。\n\(safeDiagnostic(stderr))\n",
                         color: .systemRed)
            setStatus("审查失败")
            return
        }
        let state = payload["status"] as? String
        if state == "no_changes" {
            guard status == 0,
                  let result = payload["review_result"] as? [String: Any],
                  let issues = result["issues"] as? [[String: Any]], issues.isEmpty,
                  let assessment = result["overall_assessment"] as? String,
                  !assessment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  result["coverage"] as? String == "full",
                  let knowledge = payload["knowledge_retrieval"] as? [String: Any],
                  knowledge["references"] as? [Any] != nil,
                  knowledge["warnings"] as? [String] != nil,
                  let metadata = payload["metadata"] as? [String: Any],
                  let files = metadata["changed_files"] as? [String],
                  let message = payload["message"] as? String,
                  !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                appendOutput("审查失败：空 diff 报告缺少有效字段；结果未作为通过处理。\n",
                             color: .systemRed)
                setStatus("报告不完整")
                return
            }
            appendOutput("没有可审查的改动。\n", color: .secondaryLabelColor)
            appendOutput("覆盖范围：\(files.count) 个文件；本次未执行审查。\n")
            appendOutput("知识库提示：本次未执行审查，未检索知识库。\n\n")
            setStatus("无可审查改动")
            return
        }
        if status != 0 || state == "error" || state == "needs_context" {
            let reviewResult = payload["review_result"] as? [String: Any]
            let reason = payload["error"] as? String ?? payload["question"] as? String ??
                reviewResult?["error"] as? String ??
                "CLI 以退出码 \(status) 结束。"
            appendOutput("审查失败：\(reason)\n结果未作为通过处理。\n", color: .systemRed)
            setStatus("审查失败")
            return
        }
        guard state == "complete" else {
            appendOutput("审查失败：报告缺少有效的 complete 状态；结果未作为通过处理。\n", color: .systemRed)
            setStatus("报告不完整")
            return
        }
        guard let result = payload["review_result"] as? [String: Any],
              let issues = result["issues"] as? [[String: Any]],
              result["error"] == nil else {
            appendOutput("审查失败：报告缺少有效的 review_result/issues，不能判定为通过。\n", color: .systemRed)
            setStatus("报告不完整")
            return
        }

        guard let assessment = result["overall_assessment"] as? String,
              !assessment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let recommendation = result["recommendation"] as? String,
              ["approve", "request_changes", "comment"].contains(recommendation),
              let coverage = result["coverage"] as? String,
              ["full", "partial"].contains(coverage),
              let knowledge = payload["knowledge_retrieval"] as? [String: Any],
              let references = knowledge["references"] as? [Any],
              let warnings = knowledge["warnings"] as? [String],
              let metadata = payload["metadata"] as? [String: Any],
              let repository = metadata["repository"] as? [String: Any],
              let files = repository["changed_files"] as? [String] else {
            appendOutput("审查失败：报告缺少有效结论、覆盖范围或知识库字段；结果未作为通过处理。\n",
                         color: .systemRed)
            setStatus("报告不完整")
            return
        }

        appendOutput("总体结论：\(assessment)\n", bold: true)
        appendOutput("审查建议：\(recommendation)\n")
        appendOutput("覆盖范围：\(coverage)")
        if let note = result["coverage_note"] as? String, !note.isEmpty {
            appendOutput("；\(note)")
        }
        appendOutput("（\(files.count) 个文件）")
        appendOutput("\n")

        appendOutput("知识库提示：本地索引匹配 \(references.count) 条。\n")
        for warning in warnings { appendOutput("  · \(warning)\n", color: .secondaryLabelColor) }
        if let specialist = payload["specialist_context"] as? [String: Any] {
            let scenario = specialist["scenario"] as? String ?? "通用"
            let specialistState = specialist["status"] as? String ?? "未提供"
            appendOutput("专业覆盖：\(scenario)（\(specialistState)）\n")
        }

        if issues.isEmpty {
            appendOutput("\n未发现问题。\n", color: NSColor(calibratedRed: 0.48, green: 0.92, blue: 0.78, alpha: 1), bold: true)
        } else {
            appendOutput("\n发现 \(issues.count) 个问题\n", bold: true)
            for (index, issue) in issues.enumerated() {
                let severity = issue["severity"] as? String ?? "未标记"
                let title = issue["title"] as? String ?? issue["type"] as? String ?? "未提供标题"
                let color: NSColor = ["critical", "high"].contains(severity.lowercased()) ? .systemRed :
                    severity.lowercased() == "medium" ? .systemOrange : .systemYellow
                appendOutput("\(index + 1). [\(severity.uppercased())] \(title)\n", color: color, bold: true)
                appendOutput("位置：\(issue["location"] as? String ?? "未提供")\n", color: .secondaryLabelColor)
                appendOutput("说明：\(issue["description"] as? String ?? "报告未提供说明")\n")
                appendOutput("修复建议：\(issue["suggestion"] as? String ?? "报告未提供修复建议")\n\n")
            }
        }
        appendOutput("\n")
        setStatus("完成")
    }

    private func offlineReviewHeading(_ arguments: [String]) -> String {
        arguments.contains("--offline") ? "离线代码审查" : "审查当前改动"
    }

    private func safeDiagnostic(_ data: Data) -> String {
        var detail = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        let environment = ProcessInfo.processInfo.environment
        var secrets = ["AI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"].compactMap { environment[$0] }
        let configPath = environment["REVIEWAGENT_CONFIG"] ??
            URL(fileURLWithPath: environment["REVIEWAGENT_HOME"] ??
                URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent(".reviewagent").path)
                .appendingPathComponent("ai_config.json").path
        if let config = try? Data(contentsOf: URL(fileURLWithPath: configPath)),
           let object = try? JSONSerialization.jsonObject(with: config) as? [String: Any],
           let key = object["api_key"] as? String {
            secrets.append(key)
        }
        for secret in secrets where secret.count >= 8 {
            detail = detail.replacingOccurrences(of: secret, with: "[API Key 已隐藏]")
        }
        if detail.isEmpty { return "CLI 没有提供错误详情。" }
        return String(detail.prefix(1000))
    }

    private func setControlsRunning(_ running: Bool) {
        sendButton.isEnabled = !running
        promptField.isEnabled = !running
        actionButtons.forEach { $0.isEnabled = !running }
        newConversationButton.isEnabled = !running
        clearDisplayButton.isEnabled = !running
        cancelButton.isHidden = !running
        cancelButton.isEnabled = running
    }

    private func terminate(_ process: Process) {
        process.terminate()
        DispatchQueue.global().asyncAfter(deadline: .now() + 2) {
            if process.isRunning { process.terminate() }
        }
    }

    private func stopProcessForTermination() {
        guard let process = runningProcess else { return }
        process.terminate()
        process.waitUntilExit()
        runningReaders?.wait()
        activeTaskID = nil
        runningPipes.forEach { pipe in
            pipe.fileHandleForReading.readabilityHandler = nil
            try? pipe.fileHandleForReading.close()
        }
        runningPipes = []
        runningProcess = nil
    }

    private func appendOutput(_ text: String, color: NSColor? = nil, bold: Bool = false) {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: bold ? NSFont.systemFont(ofSize: 14, weight: .semibold) :
                (outputView.font ?? NSFont.systemFont(ofSize: 14)),
            .foregroundColor: color ?? outputView.textColor ?? NSColor.white,
        ]
        outputView.textStorage?.append(NSAttributedString(string: text, attributes: attributes))
        outputView.scrollToEndOfDocument(nil)
    }

    private func setStatus(_ text: String) {
        statusLabel.stringValue = text
    }
}

let application = NSApplication.shared
let delegate = CodeVigilAgentDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
