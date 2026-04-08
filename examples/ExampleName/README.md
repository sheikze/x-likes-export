# ExampleName Example

这个目录放的是 `x-likes-export` 在一个示例 Obsidian 知识库里的集成样例。

## 文件

- [x_likes_brief.py](./x_likes_brief.py)
- [x_likes_pull.py](./x_likes_pull.py)

## 说明

- `x_likes_brief.py` 是日报/专题研报的下游整理逻辑
- `x_likes_pull.py` 是显式 opt-in 的直拉脚本
- 这两个脚本都带有示例仓库路径和规则，不是开箱即用的通用配置

如果要用于别的库，应先改：

- 根目录路径
- 输出目录
- post-import hook
- 日报/研报格式规则
