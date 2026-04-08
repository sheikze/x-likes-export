# X Likes Export

`x-likes-export` 是一个本地优先的 X/Twitter Likes 导出项目。

它的目标是：

- 复用当前浏览器里已登录的 X 会话
- 不依赖 X archive
- 直接导出自己账号的 Likes
- 输出为：
  - `Markdown`
  - `JSON`
- 可选直写 Obsidian vault

## 组成

### 1. Chrome 扩展

目录：

- [chrome_extension](./chrome_extension)

能力：

- 自动识别当前登录账号
- 打开后台 Likes 页
- 通过 X Likes GraphQL 接口分页抓取
- 导出 `md/json`
- 可选把结果 POST 给本地 bridge

### 2. 本地 bridge

脚本：

- [scripts/obsidian_bridge.py](./scripts/obsidian_bridge.py)

能力：

- 监听 `http://127.0.0.1:8767`
- 接收扩展发来的导出内容
- 直接写入指定目录
- 可选在导入完成后执行一个 post-import hook

## 安装扩展

1. 打开 Chromium 浏览器扩展页
2. 开启 `Developer mode`
3. 选择 `Load unpacked`
4. 选择：

```text
chrome_extension
```

加载后，扩展会提供：

- `popup.html`
- `status.html`

都可以触发导出。

## 使用方式

### 方式 A：只下载到本地

1. 在浏览器登录 X
2. 打开扩展
3. 点 `Export My Likes`
4. 获取：
   - `x-likes-export-<timestamp>.md`
   - `x-likes-export-<timestamp>.json`

### 方式 B：直接写入 Obsidian

先启动 bridge：

```bash
python3 scripts/obsidian_bridge.py \
  --host 127.0.0.1 \
  --port 8767 \
  --target-dir "/path/to/your/vault/raw/X Likes/source"
```

如果还希望导入后自动执行后处理脚本：

```bash
python3 scripts/obsidian_bridge.py \
  --target-dir "/path/to/your/vault/raw/X Likes/source" \
  --post-import-cmd "python3 /path/to/your/vault/scripts/x_likes_brief.py"
```

## ExampleName 示例

当前仓库里带有下游知识库集成逻辑的示例脚本放在：

- [examples/ExampleName/x_likes_brief.py](./examples/ExampleName/x_likes_brief.py)
- [examples/ExampleName/x_likes_pull.py](./examples/ExampleName/x_likes_pull.py)

这两个脚本是：

- 一个 Obsidian 知识库里的具体集成样例
- 不是通用库的最小核心

其中：

- `x_likes_brief.py`：把快照整理成单文件日报
- `x_likes_pull.py`：显式 opt-in 的直拉脚本，会读本机 Chrome cookie / keychain

## 边界

- 这个项目依赖当前浏览器已经登录 X
- 不绕过权限边界
- 不保证 X 内部接口永远不变
- 如果 X GraphQL 结构变了，需要重新适配

## 建议

如果你要把它接进自己的 Obsidian：

1. 保留扩展和 bridge 为通用层
2. 把“日报 / 研报 / 视频补充”这些逻辑放到你自己的仓库里
3. 不要把仓库私有规则硬编码进扩展本体
