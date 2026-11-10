#!/bin/bash
# 在 Mac 上把 desktop-app/CodeVigilAgentApp.swift 编译成可双击运行的
# CodeVigilAgent.app（自带后端，不需要另外装 Python 以外的依赖）。
#
# 用法：
#   chmod +x desktop-app/build-mac.sh     # 只需要做一次，给这个文件执行权限
#   ./desktop-app/build-mac.sh            # 编译，产物在 desktop-app/build/
#
# 要求：macOS 13 或更新；已安装 Xcode 命令行工具
#   （没装的话终端里执行  xcode-select --install  会弹出安装窗口）

set -euo pipefail

# 切到仓库根目录（无论从哪里调用这个脚本）
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

APP="desktop-app/build/CodeVigilAgent.app"
BIN="$APP/Contents/MacOS/CodeVigilAgent"

# ---------- 0. 环境自检 ----------
if ! command -v swiftc >/dev/null 2>&1; then
    echo "✗ 找不到 swiftc（Swift 编译器）"
    echo "  请先在终端执行：xcode-select --install"
    echo "  安装完成后重新运行本脚本。"
    exit 1
fi

echo "Swift 编译器：$(command -v swiftc)"
swiftc --version | head -1

if [ ! -f "$ROOT/ascend_cli.py" ]; then
    echo "✗ 找不到 ascend_cli.py，请确认在仓库根目录运行"
    exit 1
fi

# ---------- 1. 清理并建立 .app 骨架 ----------
echo
echo "[1/4] 清理旧产物并建立 .app 目录结构"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/backend"

# ---------- 2. 编译 Swift ----------
echo
echo "[2/4] 编译界面（CodeVigilAgentApp.swift）"
# 不指定 -target，按当前机器架构编译；Release 优化让输出区滚动更顺
swiftc -O "$ROOT/desktop-app/CodeVigilAgentApp.swift" -o "$BIN"
echo "      → $BIN"

# ---------- 3. 打包后端 ----------
echo
echo "[3/4] 拷贝 Python 后端到 Contents/Resources/backend"
# 只拷运行需要的东西，跳过依赖与缓存，避免 .app 变成几百 MB
rsync -a \
    --exclude 'node_modules' \
    --exclude '.git' \
    --exclude 'desktop-app/build' \
    --exclude '__pycache__' \
    --exclude '.workbuddy' \
    "$ROOT"/ "$APP/Contents/Resources/backend/"
echo "      → $(du -sh "$APP/Contents/Resources/backend" | cut -f1)"

# ---------- 4. 写 Info.plist 并签名 ----------
echo
echo "[4/4] 写入 Info.plist 并做本地签名"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleDevelopmentRegion</key><string>zh_CN</string>
<key>CFBundleDisplayName</key><string>CodeVigil Agent</string>
<key>CFBundleExecutable</key><string>CodeVigilAgent</string>
<key>CFBundleIdentifier</key><string>com.codevigilagent.desktop</string>
<key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
<key>CFBundleName</key><string>CodeVigil Agent</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.0.0</string>
<key>CFBundleVersion</key><string>1.0.0</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

# ad-hoc 签名：不签名的话 macOS 会直接拒绝启动
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || \
    echo "      ! 签名失败，首次打开时可能需要在「系统设置 → 隐私与安全性」里放行"

echo
echo "================================================"
echo "✓ 编译完成"
echo "  产物：$ROOT/$APP"
echo
echo "  双击打开："
echo "    open \"$ROOT/$APP\""
echo
echo "  如果提示「无法打开，因为无法验证开发者」："
echo "    右键点这个 .app → 打开 → 再点一次「打开」"
echo "================================================"
