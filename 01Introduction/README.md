# ReAct 课堂代码作业：两阶段数学锁

本项目使用同一个智谱免费模型、同一道题和同一个评分器，比较两种运行方式：

1. **Direct**：只调用模型一次，不提供计算器，也没有第二次尝试。
2. **ReAct**：模型先计算中间值，读取 Observation 后选择分支，再计算最终答案。

题目不依赖外部文档，只开放一个安全计算器。理想轨迹只有两次
`Calculate` 和一次 `Finish`，因此适合在课堂上直接展示 ReAct 的多轮闭环。

## 挑战题

门禁系统按下面规则生成六位验证码：

```text
1. S = 20250807^123457 mod 1000000
2. 观察 S：
   - S 为偶数：C = (S × 2026 + 314159) mod 1000000
   - S 为奇数：C = (S × 2025 + 271828) mod 1000000
3. 输出 {"answer":"......"}
```

Direct 必须在没有计算器的情况下，一次性完成大指数模运算、判断奇偶并执行正确分支，
弱模型无法稳定得到可通过精确评分的答案。ReAct 则形成真正的依赖链：

```text
Calculate seed → Observation: 730807 → choose odd branch
→ Calculate final code → Observation: 156003 → Finish
```

这里的关键不是“多写几步思维”，而是下一次 Action 确实依赖上一次外部工具返回的
Observation。

官方资料：

- [智谱快速开始](https://docs.bigmodel.cn/cn/guide/start/quick-start)
- [免费模型 GLM-4-Flash-250414](https://docs.bigmodel.cn/cn/guide/models/free/glm-4-flash-250414)
- [ReAct 原论文](https://arxiv.org/abs/2210.03629)

## 学习目标

完成后，学生应该能够：

- 区分一次性 Direct inference 与 ReAct 循环；
- 解析 `Calculate[...]` 和 `Finish[...]`；
- 将工具结果作为 Observation 放回上下文；
- 根据 Observation 动态选择下一步 Action；
- 使用步数预算、工具白名单和 Finish verifier 防止假成功。

## 项目结构

```text
course_code/
├── main.py              # Direct / ReAct / Compare 入口
├── zhipu_client.py      # 智谱 HTTP API 客户端
├── direct_agent.py      # 一次直推基线
├── react_agent.py       # 完整参考实现
├── react_starter.py     # 学生 TODO 版本
├── tools.py             # 安全计算器
├── task.py              # 两种模式看到的同一道题
├── grader.py            # 答案与过程评分
├── mock_client.py       # 免费离线演示
├── tests/               # 离线单元测试
└── INSTRUCTOR_NOTES.md  # 教师答案与课堂安排
```

如果不希望学生提前看到答案，分发时可移除 `react_agent.py`、
`INSTRUCTOR_NOTES.md`，并隐藏 `grader.py` 中的预期答案。

## 环境与 API Key

要求 Python 3.10 或更高版本。项目只使用标准库，不需要安装第三方依赖。

```bash
cd /home/yiyunzhou/course/course_code
export ZAI_API_KEY="你的 API Key"
export ZAI_MODEL="glm-4-flash-250414"
```

不要把真实 API Key 写入代码、README、截图或 Git 仓库。

## 零费用离线检查

```bash
python3 main.py --mode compare --offline
python3 -m unittest discover -s tests -v
```

预期结果：Direct 失败；ReAct 用 3 个回合完成两次计算并得到 `PASS — 12/12`。

### 真实 GLM-4-Flash 验证（2026-08-06）

首次运行时，模型连续输出数学习惯写法
`20250807^123457 % 1000000`，而安全计算器只接受 `pow(...)`，因此在 6 步后失败。
这一次失败尚未进入 Finish，不是 JSON 解析问题。

在 Harness 中增加受限的 `base^exponent % modulus` 转换后重试：

- Direct 输出格式正确但结果错误的 `{"answer":"826085"}`，得到 `2/10`；
- ReAct 第 1 轮得到 `730807`，第 2 轮得到 `156003`；
- 第 3 轮输出 `Finish[{"answer":"156003"}]`，JSON 成功解析，最终 `12/12`。

两次真实轨迹保存在 `runs/math_live.json` 和
`runs/math_live_retry1.json`，其中不包含 API Key。

## 运行真实模型

先运行一次性基线：

```bash
python3 main.py --mode direct
```

再运行 ReAct：

```bash
python3 main.py --mode react --max-steps 6
```

同时比较并保存轨迹：

```bash
python3 main.py --mode compare --max-steps 6 \
  --trace-out runs/comparison.json
```

轨迹文件包含模型输出、Action、Observation 和评分，不保存 API Key。

## 学生编码任务

不要先看 `react_agent.py`。打开 `react_starter.py`，完成三个 TODO。

### TODO 1：定义 Action 协议

系统提示必须规定：

- 每轮只允许一个 Action；
- `Calculate[numeric expression]` 调用计算器；
- `Finish[{"answer":"......"}]` 提交答案；
- 必须先计算 S，根据 Observation 判断奇偶，再计算相应分支。

### TODO 2：实现循环

每轮调用模型、解析 Action、执行白名单工具，并把结果作为新的 Observation
追加到 messages。不要使用 `eval()` 执行模型生成的内容。

### TODO 3：实现可靠停止

只有在两阶段计算均完成且答案通过固定验证时，才能接受 Finish；否则把错误作为
Observation 返回模型继续修正。达到 6 步预算后必须停止。

运行学生版本：

```bash
python3 main.py --mode react --implementation starter --offline
python3 main.py --mode react --implementation starter
```

## 参考轨迹

```text
Thought: I first need the exact seed before choosing a branch.
Action: Calculate[pow(20250807,123457,1000000)]
Observation: 730807

Thought: S is odd, so I must use the odd branch.
Action: Calculate[(730807 * 2025 + 271828) % 1000000]
Observation: 156003

Thought: The second observation is the exact final code.
Action: Finish[{"answer":"156003"}]
```

安全计算器支持基本算术、三参数 `pow(base, exponent, modulus)`，以及弱模型常用的
`base^exponent % modulus` 模幂简写；文件操作、模块导入、
任意函数调用以及会产生巨大中间数的普通幂运算都会被拒绝。
