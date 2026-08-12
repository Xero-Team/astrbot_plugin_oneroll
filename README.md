# astrbot_plugin_oneroll

OneRoll 的 AstrBot 薄封装。插件把表达式解析、随机数生成和资源预算交给
[HydroRoll-Team/OneRoll](https://github.com/HydroRoll-Team/OneRoll)，本项目只负责
AstrBot 指令、配置校验和聊天消息格式化。

## 快速开始

本仓库使用 uv 管理开发环境，并固定在 Python `3.14.6`（项目要求
`>=3.14,<3.15`）：

```bash
uv sync
uv run python --version
```

在 AstrBot 源码 checkout 根目录中安装插件。将 `<plugin-dir>` 替换为本插件目录：

```bash
uv run astrbot plug install --editable <plugin-dir>
```

运行时依赖为 `oneroll>=1.3.5,<2`。OneRoll 的 Rust 扩展由对应 Python wheel
提供，安装完成后重载 AstrBot 即可。

## 指令

| 指令 | 别名 | 作用 |
| --- | --- | --- |
| `/roll [表达式]` | `/r` | 计算一条表达式，或计算以分号分隔的 OneRoll 程序 |
| `/roll_stats <次数> <表达式>` | `/rs` | 在共享资源预算内重复计算一条表达式并显示统计值 |
| `/roll_help` | `/rhelp` | 显示帮助文案 |

省略 `/roll` 的表达式时，使用配置项 `default_expression`（默认 `1d20`）。
统计命令的次数必须在 `1` 到 `max_batch_times`（默认 `20`）之间；统计表达式
本身应是单条表达式，不能写成多指令程序。

常用示例：

```text
/r 1d20+5
/r 4d6kh3
/r '4d6kh3 # 属性检定'
/r '1d20+5; 2d6; 1d8 # 同一程序中的三条指令'
/rs 20 2d6+3
```

AstrBot 会先用 Orbit 解析命令参数。`#`、`;`、`|`、`$` 等字符可能被 Orbit
当作命令语法，因此带注释或多指令程序时，请把完整表达式放在单引号或双引号中，
也可以按 Orbit 规则使用反斜杠转义。

## OneRoll 表达式

下面是 OneRoll 当前 1.x 语法的范围。插件不会再实现一套独立的骰子解析器，最终
是否接受、具体错误和边界行为都以安装的 OneRoll 版本为准。

### 基本项和运算符

- 整数：支持有符号的十进制整数，例如 `7`、`-2`。
- 骰子：`<数量>d<面数>`，数量和面数都必须大于零，例如 `1d20`、`4d6`、`2d8`。
  数量必须显式写出；原生 OneRoll 不接受 `d20`。
- 运算符：`+`、`-`、`*`、`/`、`^`。
- 括号：使用 `(...)` 明确分组，例如 `(1d20 + 5) * 2`。
- 除法是整数除法并向零截断，例如 `5 / 2` 的结果是 `2`；除零、溢出和非法
  指数会被 OneRoll 拒绝。

OneRoll 1.x 的二元运算按兼容性规则从左到右构造，未采用通常的数学优先级；例如
`1 + 2 * 3` 当前得到 `9`。复杂表达式请主动使用括号，不要依赖未加括号的优先级。
幂运算链也按当前 1.x 的左结合行为处理。

### 注释和程序

- `#` 开始一段注释，注释只放在表达式或整个程序的末尾，例如
  `1d20+5 # attack`。
- 程序使用 `;` 分隔一条或多条指令，例如
  `1d20 + 5; 2d6; 1d8 # encounter`。
- 程序不能有空指令：`1d6;` 和 `1d6;;2d6` 都是无效输入。
- 程序中的所有指令共享同一个 OneRoll 资源预算，拆成多条指令不会绕过限制。

### 骰子修饰符

修饰符紧跟在骰子后面，可以连续组合，例如 `4d6kh3`。组合行为遵循 OneRoll
1.x 的兼容实现，修饰符的先后顺序会影响结果。

| 写法 | 含义 |
| --- | --- |
| `!`、`e` | 爆炸骰：掷出该骰最大面数时继续追加结果；`e` 是别名 |
| `K<n>` | 爆炸后取最高 `n` 个值；当前 1.x 对该组合存在兼容性缺陷，实际行为以引擎版本为准 |
| `r<n>` | 值小于等于 `n` 时重掷一次并用替代值 |
| `ro<n>` | 条件重掷一次；当前 1.x 的可观察行为与 `r<n>` 相同 |
| `R<n>` | 一直重掷到值大于 `n`；循环受共享资源预算限制 |
| `a<n>` | 值小于等于 `n` 时重掷，并把替代值加到原值上 |
| `k<n>`、`kh<n>` | 保留最高的 `n` 个值；`k` 是 `kh` 的别名 |
| `kl<n>` | 保留最低的 `n` 个值 |
| `dh<n>` | 丢弃最高的 `n` 个值 |
| `dl<n>` | 丢弃最低的 `n` 个值 |
| `u` | 去重，重复值只保留一份，不会补掷 |
| `s` | 将最终骰面按升序排列 |
| `c<n>` | 统计最终骰面中恰好等于 `n` 的数量，并返回一个汇总值 |

示例：

```text
2d20kh1       # 优势式取高（两骰取最高一骰）
2d20kl1       # 取低
4d6kh3        # 四个 d6 取最高三个
8d6dl2        # 八个 d6 丢弃最低两个
1d6!          # 掷出 6 时继续爆炸
10d6c6         # 统计掷出 6 的次数
4d6u          # 去重后的骰面
8d6s          # 升序排列骰面
```

### 严格语法与便利写法

配置项 `strict_syntax` 默认开启。开启时，插件把输入原样交给 OneRoll，推荐在
需要验证或共享表达式时保持开启。关闭时，插件只额外提供一项兼容便利：把独立的
`d20` 改写为 `1d20`；其他语法仍由 OneRoll 校验，不会自动转换成 Roll20、D&D 或
其他骰子机器人的方言。

因此，下列常见写法不是本插件承诺的语法，除非 OneRoll 将来明确加入：`adv/dis`、
比较目标如 `>=15`、Fate 的 `dF`、未列出的 `!!` 或其他平台专用函数、变量和条件块。
OneRoll 2.0 规划中的范围骰、加权列表、变量、函数和条件语法也不属于当前 1.x 支持范围。

## 返回结果

`/roll` 会显示表达式和总点数；`show_details`、`show_rolls` 控制是否附加 OneRoll
的计算明细和骰面列表。表达式末尾的 `# 注释` 会显示在结果中，程序的末尾注释会
单独显示为程序注释。

`/roll_stats` 返回投掷次数、最小值、最大值、平均值和总和。批量样本共用同一个
`batch_samples`、生成值和工作量预算；资源耗尽时不会返回部分统计结果。

## 配置

所有配置都在插件配置页中提供，也可以编辑生成的配置文件。`_conf_schema.json` 使用
严格 JSON；AstrBot 会根据 schema 补齐默认项、整理顺序并移除未知项，插件运行时还会
再次校验边界。

| 配置项 | 默认值 | 说明 |
| --- | ---: | --- |
| `default_expression` | `1d20` | `/roll` 未提供表达式时使用 |
| `strict_syntax` | `true` | 是否完全使用 OneRoll 原生语法 |
| `max_input_length` | `256` | 表达式最大 UTF-8 字节数，范围 `32`–`4096` |
| `max_batch_times` | `20` | `/roll_stats` 最大次数，范围 `1`–`100` |
| `show_details` | `true` | 是否显示计算明细 |
| `show_rolls` | `true` | 是否显示骰面列表 |
| `max_generated_values` | `10000` | OneRoll 生成值上限，范围 `1`–`1000000` |
| `max_work_units` | `1000000` | OneRoll 工作量上限，范围 `100`–`50000000` |
| `max_output_bytes` | `1048576` | OneRoll 结构化输出字节上限 |
| `max_message_length` | `4000` | 发送到聊天平台的消息长度上限 |

### 配置回复文案

`messages` 对象中的模板可以直接改成自己的语言或格式。可用占位符如下：

| 字段 | 可用占位符 |
| --- | --- |
| `batch_range_error` | `{max_times}` |
| `result_header`、`stats_header` | `{expression}` |
| `result_total`、`stats_total` | `{total}` |
| `result_details` | `{details}` |
| `result_rolls` | `{rolls}` |
| `result_comment`、`program_comment` | `{comment}` |
| `stats_count` | `{count}` |
| `stats_minimum` | `{minimum}` |
| `stats_maximum` | `{maximum}` |
| `stats_mean` | `{mean}`，支持格式说明如 `{mean:.2f}` |

`help`、`dependency_error` 和 `roll_error` 是纯文本字段。模板为空、过长或占位符
拼写错误时，会安全回退到默认文案；不要在模板中放入 NUL 字符。

插件只把 `generated_values`、`work_units`、`output_bytes` 和 `batch_samples` 这四项
资源上限传给 OneRoll；OneRoll 其他解析、AST、嵌套和随机数预算仍由引擎自己的安全默认值
保护。所有资源限制都是单次请求共享的，超限会原子失败并返回统一错误提示。

## 兼容性与开发

插件只使用 `astrbot.api` 公共 SDK，不依赖具体消息平台或 AstrBot 内部模块。当前开发
基线与目标 AstrBot checkout 一致：Python `>=3.14`（开发 pin `3.14.6`）。

本地检查命令：

```bash
python .agents/skills/create-astrbot-plugin/scripts/check_plugin.py \
  --astrbot-root <astrbot-checkout> <plugin-dir>
uv run python -m compileall -q main.py core.py tests
uv run ruff check main.py core.py tests
uv run ruff format --check main.py core.py tests
uv run pytest -q
```

## 上游资料和许可证

- OneRoll：<https://github.com/HydroRoll-Team/OneRoll>
- OneRoll 语法以上游仓库中的 `grammar.pest` 和 1.x language guide 为准。
- OneRoll 资源限制说明：<https://github.com/HydroRoll-Team/OneRoll/blob/dev/docs/source/limits.rst>

本插件沿用仓库中的 AGPL-3.0 许可证；OneRoll 同样以 AGPL-3.0 发布。
