# Introduction to Agentic AI：Direct vs. ReAct 课堂作业

本目录包含一份面向 Introduction to Agentic AI 课程的 ReAct 实操作业。学生将让同一个模型分别以 Direct 和 ReAct 两种方式修正校园活动方案，并观察外部验证、Few-shot 与 Reflection 如何影响后续推理。

## 文件说明

- [`Introduction_ReAct_Teacher.ipynb`](./Introduction_ReAct_Teacher.ipynb)：教师版，包含中文教学说明、参考实现、标准离线轨迹和唯一解。
- [`Introduction_ReAct_Learner.ipynb`](./Introduction_ReAct_Learner.ipynb)：英文学生版，保留三个待完成函数，不包含参考实现。
- `README.md`：环境配置、课堂任务、运行方法和验收标准。

两份 Notebook 使用相同任务、工具和 ReAct 框架。课堂发放时使用 Learner 版；讲解参考答案、演示标准轨迹或验收时使用 Teacher 版。两份文件默认均设置为 `USE_REAL_API=False`。

## 学习目标

完成作业后，学生应能够：

1. 解释 `Thought → Action → Observation` 的基本循环；
2. 区分一次生成的 Direct 方法与可调用工具的 ReAct 方法；
3. 使用 Few-shot 示例约束模型的推理和 Action 格式；
4. 根据 Verifier 返回的 Observation 构造 Reflection；
5. 理解 Action 解析、JSON 校验、工具执行与步数限制在 Agent Harness 中的作用。

## 任务背景

学校需要为 150 人的工作坊选择场地。方案必须同时满足以下条件：

- 提供轮椅通道；
- 提供投影设备，外租投影仪费用为 250 元；
- 活动持续 2 小时，并在 18:00 前结束；
- 讲者只能在 14:00 或 16:00 开始；
- 总费用不超过 1400 元。

候选场地如下：

| 场地   | 容量 | 轮椅通道 | 内置投影 | 可用开始时间 | 场地费 |
| ------ | ---: | :------: | :------: | ------------ | -----: |
| Hall A |  120 |    是    |    是    | 14:00、16:00 |    900 |
| Hall B |  180 |    是    |    否    | 14:00        |   1000 |
| Hall C |  160 |    否    |    是    | 16:00        |    800 |
| Hall D |  200 |    是    |    是    | 15:00        |   1300 |

初始方案为：

```json
{"venue": "Hall C", "start": "16:00", "rent_projector": false}
```

Agent 需要发现其中的约束冲突，修正方案，计算费用，并提交经过验证的最终 JSON。

## 学生需要完成的内容

底层 ReAct 循环、Action 解析、工具执行、JSON 容错和步数限制均已提供。学生重点完成三个与 Reasoning 相关的函数。

### 1. `build_reasoning_prompt(constraints)`

编写 ReAct 的 System Prompt，使模型能够：

- 首先验证完整的初始方案；
- 根据最新 Observation 决定下一步；
- 每轮只输出一个 Action；
- 在 `VerifyPlan` 中提供完整的 `venue`、`start` 和 `rent_projector` 字段；
- 方案通过验证并完成费用计算后才能执行 `Finish`。

### 2. `build_few_shot_messages()`

提供一个规模更小的方案修正示例，展示完整协议：

```text
VerifyPlan → Observation → Reflection → VerifyPlan → Calculate → Finish
```

Few-shot 的作用不仅是展示输出格式，还要示范如何保留正确字段、修改违规字段并继续执行下一步。

### 3. `build_reflection(feedback, previous_plan)`

根据 Verifier 的失败反馈生成以 `Reflection:` 开头的消息。Reflection 应当：

- 引用上一次方案和具体违规原因；
- 说明哪些字段可以保留；
- 指出哪些字段必须修改；
- 提醒模型不要重复已知的永久性冲突；
- 要求下一次 `VerifyPlan` 使用完整 JSON。

本作业不要求学生实现网络请求、验证器、计算器、正则解析器或循环控制。

## 可用工具与 Action 格式

模型每轮只能选择一个 Action：

```text
Action: VerifyPlan[{"venue":"...","start":"...","rent_projector":false}]
Action: Calculate[1000+250]
Action: Finish[{"venue":"...","start":"...","rent_projector":true,"total_cost":1250}]
```

- `VerifyPlan[JSON]`：检查容量、无障碍、设备、场地时间、讲者时间和预算；
- `Calculate[expression]`：使用安全计算器计算最终费用；
- `Finish[JSON]`：提交最终方案。只有方案已经通过验证且费用来自计算器时才能成功。

## 环境要求

- Python 3.9 或更高版本；
- VS Code + Jupyter 扩展，或 Jupyter Notebook/Lab；
- 真实 API 模式需要网络连接和可用的智谱 API Key；
- 代码仅使用 Python 标准库，不需要安装 其他第三方依赖。

## 运行模式

Notebook 开头包含以下设置：

```python
MODEL = os.getenv("ZAI_MODEL", "glm-4-flash-250414")
USE_REAL_API = True
MAX_STEPS = 12
```

### 离线课堂模式

建议先使用确定性的离线模式：

```python
USE_REAL_API = False
```

离线模式不会请求 API，也不需要 API Key。所有学生会得到相同轨迹，适合课堂讲解和统一验收。

### 真实 API 模式

需要比较真实模型表现时设置：

```python
USE_REAL_API = True
```

默认模型为 `glm-4-flash-250414`，也可以通过环境变量 `ZAI_MODEL` 更换模型。智谱 API 使用方法可参考[官方快速开始文档](https://docs.bigmodel.cn/cn/guide/start/quick-start)。

## API Key 配置

### 获取智谱 API Key

1. 访问[智谱 AI 开放平台](https://bigmodel.cn/)，使用手机号或邮箱注册并登录账户。
2. 登录后进入个人中心的 [**API Keys** 页面](https://bigmodel.cn/apikey/platform)。
3. 点击“新建 API Key”，生成属于自己的密钥。
4. 复制并妥善保存密钥。不要将它发布到聊天记录、代码仓库、截图或需要提交的 Notebook 中。

### 推荐方式：通过环境变量传入

Linux/macOS：

```bash
export ZAI_API_KEY="你的API Key"
```

Windows PowerShell：

```powershell
$env:ZAI_API_KEY="你的API Key"
```

VS Code 必须从设置了环境变量的同一个终端启动。如果 VS Code 已经打开，请完全关闭后重新启动。

### 课堂临时方式：`getpass()`

当 `USE_REAL_API=True` 且没有检测到 `ZAI_API_KEY` 时，Notebook 会执行：

```python
from getpass import getpass
api_key = getpass("Zhipu API Key（输入内容不会显示）: ")
```

输入的 Key 不会显示，也不会写入 Notebook 输出。如果 VS Code 中没有出现输入框，建议改用环境变量方式，然后重启 Kernel。

不要把真实 Key 写入以下位置：

- Notebook 普通代码字符串；
- `%env` 单元格；
- `os.environ[...]` 赋值语句；
- README、截图或提交文件。

课堂结束后应执行 **Restart Kernel**。共享的课堂 Key 应定期轮换。

## 建议运行顺序

1. 学生打开 `Introduction_ReAct_Learner.ipynb`；教师演示时打开 `Introduction_ReAct_Teacher.ipynb`；
2. 选择 Python Kernel；
3. 首次运行建议设置 `USE_REAL_API=False`；
4. 运行 Direct 部分，观察一次生成的结果；
5. 阅读 Verifier 和 Calculator 的返回结果；
6. 完成三个 Reasoning 函数；
7. 运行 ReAct 框架并查看每一步的 Thought、Action、Observation 和 Reflection；
8. 确认最终输出显示 `pass=True`；
9. 如需扩展实验，再切换至 `USE_REAL_API=True` 与真实模型比较。

## 验收标准

### 离线模式

标准离线轨迹应满足：

- Direct 一次生成未通过最终验证；
- ReAct 首先验证初始方案；
- 至少出现一次 `INVALID` Observation 和相应 Reflection；
- 有效方案通过 `VerifyPlan`；
- 最终费用由 `Calculate` 得到；
- `Finish` 返回完整 JSON；
- 最终显示 `ReAct: ... pass=True`。

离线参考轨迹包含 5 步，并通过两次失败反馈修正方案。

### 真实 API 模式

真实模型的候选方案、Reflection 次数和总步数可能不同，不要求与离线轨迹完全一致，但必须满足：

- 至少根据一次 Verifier 反馈修改方案；
- 不以未验证方案直接 Finish；
- 最终方案满足所有约束；
- 最终费用来自 Calculator；
- 在 `MAX_STEPS` 内显示 `pass=True`。

<details>
<summary>教师验收参考：唯一有效方案</summary>

```json
{
  "venue": "Hall B",
  "start": "14:00",
  "rent_projector": true,
  "total_cost": 1250
}
```

Hall A 容量不足；Hall C 不提供轮椅通道；Hall D 的 15:00 与讲者时间冲突。Hall B 在 14:00 可用，租用投影仪后总费用为 `1000 + 250 = 1250`。穷举验证器支持的所有组合后，该方案是唯一有效解。

</details>

## 常见问题

### 运行后立即显示 `complete_*_TODO`

对应函数仍为空、返回 `None`，或者 Few-shot 消息数量不足。检查三个任务函数是否已经实现。

### 模型一直遗漏 JSON 字段

在 System Prompt、Few-shot 和 Reflection 中明确要求每次 `VerifyPlan` 都包含：

```text
venue, start, rent_projector
```

### ReAct 找到有效方案但最终仍为 `max_steps`

模型可能在无效方案上消耗了过多步骤。检查 Few-shot 是否展示完整流程、Reflection 是否阻止重复失败，并确认 `MAX_STEPS=12`。

### JSON 看起来正确但无法解析

确保每轮只输出一个 Action，JSON 使用双引号，并且布尔值写成小写 `true` 或 `false`。

### Direct 偶尔也得到正确答案

真实模型具有随机性，Direct 偶尔通过不代表 ReAct 失效。课堂重点是比较两种方法的过程：Direct 没有外部反馈与恢复机会，而 ReAct 能验证、观察并修正。

### VS Code 显示的内容不是最新版本

选择 **File → Revert File** 或重新打开 Notebook，从磁盘加载最新内容，避免旧编辑器缓存覆盖文件。

## 提交要求

学生只需提交完成后的：

```text
Introduction_ReAct_Learner.ipynb
```

提交前请确认：

- Notebook 可以从头运行；
- 最终结果显示 `pass=True`；
- 三个 Reasoning 函数均已完成；
- 文件中没有 API Key；
- 不需要提交额外 Python 文件或依赖目录。
