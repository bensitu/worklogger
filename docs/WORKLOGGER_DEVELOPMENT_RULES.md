# WorkLogger 项目开发规范与架构文档

本文档由 AI 根据项目实际代码逆向生成，用于后续开发的规范约束。

## 1. 项目架构概览

### 1.1 项目定位

- 项目名称：WorkLogger。
- 项目类型：隐私优先的 Python 桌面应用。
- 主要功能：工时记录、自动记录、日历、快速日志、每日笔记、日报/周报/月报、分析图表、CSV/ICS/Markdown/PDF 导入导出、数据库备份恢复、多用户认证、AI 辅助、本地模型管理、多语言界面。
- GUI 技术：PySide6 / Qt Widgets。
- 本地存储：SQLite，直接使用 Python 标准库 `sqlite3`。
- 国际化：gettext-only i18n。
- 打包目标：PyInstaller。

### 1.2 分层架构

当前项目使用严格四层结构：

```text
worklogger/
  domain/          领域层
  app/             应用层
  infrastructure/  基础设施层
  presentation/    表现层
```

各层职责如下：

| 层     | 目录                          | 职责                                                                     | 关键约束                                            |
| ----- | --------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------- |
| 领域层   | `worklogger/domain`         | 实体、值对象、领域规则、仓储 Protocol                                                | 不导入 PySide6、sqlite3、`worklogger.infrastructure` |
| 应用层   | `worklogger/app`            | Commands、Queries、Use Cases、Ports、EventBus、JobRunner contract           | 不导入 Qt Widgets，不直接使用 sqlite3                    |
| 基础设施层 | `worklogger/infrastructure` | SQLite、迁移、Repository 实现、AI、Identity、Export、Backup、Security、Update、i18n | 实现领域层/应用层定义的协议或调用约定                             |
| 表现层   | `worklogger/presentation`   | Qt Dialog、主窗口、ViewModel、自定义 Widget、工作流 Controller                      | 不直接导入 sqlite3，不拥有数据库规则                          |
| 组合根   | `worklogger/bootstrap.py`   | 组装数据库、Repository、Use Case、ViewModel、Controller、Qt Window               | 运行时依赖集中注入                                       |
| 入口    | `worklogger/main.py`        | CLI、smoke checks、桌面启动循环                                                | 无参数默认启动桌面                                       |

### 1.3 层间通信

- UI 与用户交互使用 Qt Widgets 和 Qt `Signal`。
- Dialog/Widget 通过信号把动作传给 Controller 或内部处理函数。
- ViewModel 不依赖 Qt，主要通过普通方法接收输入并返回 `Result[T]`。
- Use Case Handler 以 `handle(command_or_query)` 方式执行应用流程。
- 领域规则以纯函数或 dataclass 模型表达。
- Repository Protocol 位于 `domain/**/repositories.py`，SQLite 实现位于 `infrastructure/repositories/*_sqlite.py`。
- 跨组件事件使用 `worklogger.app.event_bus.EventBus`，当前已有 `WorkLogSaved` 等事件。
- 长耗时任务的抽象端口是 `worklogger.app.job_runner.JobRunner`。Qt 表现层使用 `worklogger.presentation.job_runner.QtJobRunner` 将耗时任务提交到 Qt thread pool，并把完成回调派发回 UI 线程。

### 1.4 启动流程

当前入口：

```powershell
python worklogger/main.py
python -m worklogger.main
```

无参数会启动桌面应用。`--desktop` 与无参数等价。

启动流程：

1. `worklogger/main.py` 解析 CLI 参数。
2. `main()` 调用 `run_desktop()`。
3. `run_desktop()` 调用 `build_authenticated_desktop_runtime()`。
4. `bootstrap.py` 准备 SQLite 数据库、运行迁移、创建 Repository。
5. `bootstrap.py` 创建 Auth ViewModel 和 AuthController。
6. 登录、注册或 remember-me 认证成功后，组装当前用户的 ViewModel、Controller、AppWindow 或 MinimalView。
7. 窗口刷新、显示，进入 Qt event loop。
8. 用户 logout 时清理 remember token，关闭当前窗口并回到认证流程。

保留的自动化入口：

```powershell
python worklogger/main.py --help
python worklogger/main.py --smoke-import
python worklogger/main.py --smoke-startup
python -m worklogger.main --smoke-runtime
```

## 2. 目录结构规范

### 2.1 根目录

| 路径                   | 职责                                        |
| -------------------- | ----------------------------------------- |
| `.gitignore`         | Python、PyInstaller、数据库、本地配置、本地模型、测试产物忽略规则 |
| `README.md`          | 项目说明                                      |
| `CHANGELOG.md`       | 变更记录                                      |
| `LICENSE`            | 许可证                                       |
| `requirements.txt`   | 依赖清单                                      |
| `SECURITY.md`        | 安全说明                                      |
| `CONTRIBUTING.md`    | 贡献说明                                      |
| `CODE_OF_CONDUCT.md` | 行为准则                                      |
| `model_catalog.json` | 本地模型目录来源文件                                |
| `docs/`              | 项目文档                                      |
| `scripts/`           | 项目脚本，目前主要是 i18n 脚本                        |
| `tests/`             | 分层测试                                      |
| `worklogger/`        | 应用包                                       |

### 2.2 `worklogger/app`

| 路径              | 职责                                           |
| --------------- | -------------------------------------------- |
| `commands/`     | 写操作 DTO，文件命名为 `<feature>_commands.py`        |
| `queries/`      | 读操作 DTO，文件命名为 `<feature>_queries.py`         |
| `use_cases/`    | 应用层 Handler，文件按功能命名，如 `work_logs.py`、`ai.py` |
| `container.py`  | 简单依赖容器                                       |
| `event_bus.py`  | 应用事件总线                                       |
| `job_runner.py` | 长任务和取消的抽象 contract                           |
| `ports.py`      | AI、Backup、KeyStore、LocalModel 等应用端口          |

Command/Query 使用 `@dataclass(frozen=True)`。

### 2.3 `worklogger/domain`

| 路径                          | 职责                       |
| --------------------------- | ------------------------ |
| `<feature>/models.py`       | 领域模型和值对象                 |
| `<feature>/rules.py`        | 纯领域规则                    |
| `<feature>/repositories.py` | Repository Protocol      |
| `shared/errors.py`          | typed application errors |
| `shared/result.py`          | `Result[T]`              |

领域层必须保持纯 Python，不能引入 UI、SQLite、文件对话框、网络客户端或基础设施实现。

### 2.4 `worklogger/infrastructure`

| 路径                     | 职责                                                |
| ---------------------- | ------------------------------------------------- |
| `database/`            | SQLite connection、路径、安全权限、迁移、UnitOfWork           |
| `database/migrations/` | 幂等迁移文件，当前命名为 `migration_001_initial_schema.py`    |
| `repositories/`        | SQLite Repository 实现，文件命名为 `<feature>_sqlite.py`  |
| `backup/`              | SQLite backup/restore                             |
| `calendar/`            | holidays provider、ICS import                      |
| `export/`              | CSV、ICS、Markdown、Analytics CSV/PDF export/import  |
| `security/`            | password hasher、key store、remember-session store  |
| `ai/`                  | external AI adapter、local adapter、routing gateway |
| `identity/`            | OIDC、PKCE、provider config                         |
| `local_model/`         | local model catalog/storage/download/import       |
| `templates/`           | built-in 和 user template provider                 |
| `i18n.py`              | gettext runtime helpers                           |
| `update.py`            | GitHub release update checker                     |

Repository 实现可以使用 `sqlite3`，但返回 domain object 或 DTO，不能把 `sqlite3.Row` 暴露给上层。

### 2.5 `worklogger/presentation`

| 路径                 | 职责                                                                     |
| ------------------ | ---------------------------------------------------------------------- |
| `shell/`           | `AppWindow`、`MinimalView`、residency controller                         |
| `auth/`            | 登录、注册、重置、改密 Dialog 和 Controller                                        |
| `settings/`        | Settings Dialog 和 workflow controller                                  |
| `notes/`           | Note editor Dialog 和 workflow controller                               |
| `reporting/`       | Report Dialog 和 workflow controller                                    |
| `quick_logs/`      | Quick Log Dialog 和 workflow controller                                 |
| `analytics/`       | Analytics Dialog 和 workflow controller                                 |
| `ai/`              | AI Assist Dialog 和 workflow controller                                 |
| `identity/`        | Identity management Dialog 和 controller                                |
| `local_models/`    | Local model Dialog 和 controller                                        |
| `user_management/` | User management Dialog                                                 |
| `viewmodels/`      | 纯 Python ViewModel                                                     |
| `widgets/`         | 可复用 Qt Widget，如 calendar、combo_chart、switch_button、stats、worklog_entry |
| `theme/`           | ThemeEngine                                                            |

UI 文件当前全部用 Python 代码手写。当前项目未使用 Qt Designer `.ui` 文件。

### 2.6 资源文件

| 路径                                                      | 职责                                 |
| ------------------------------------------------------- | ---------------------------------- |
| `worklogger/assets/fonts/`                              | NotoSans 多语言字体                     |
| `worklogger/assets/icons/`                              | `worklogger.ico`、`worklogger.icns` |
| `worklogger/assets/images/`                             | Google/Microsoft SVG               |
| `worklogger/locales/messages.pot`                       | gettext POT                        |
| `worklogger/locales/<language>/LC_MESSAGES/messages.po` | PO catalog                         |
| `worklogger/locales/<language>/LC_MESSAGES/messages.mo` | 编译后的 gettext catalog               |

### 2.7 命名规则

- 不得在实现名、运行时 artifact、表名、配置键、类名、函数名、文件名中引入 `v4` 或 `V4`。
- 测试文件不得使用 `test_phase_*` 这类阶段命名，必须按功能或层命名。
- SQLite Repository 文件使用 `<feature>_sqlite.py`。
- Commands 文件使用 `<feature>_commands.py`。
- Queries 文件使用 `<feature>_queries.py`。
- Dialog 文件通常为 `dialog.py` 或 `dialogs.py`，Controller 文件为 `controller.py`。
- ViewModel 文件按功能命名，类名使用 `<Feature>ViewModel`。
- Controller 类名使用 `<Feature>Controller` 或 `<Feature>WorkflowController`，例如 `SettingsWorkflowController`。

## 3. 编码规范与风格约束

### 3.1 Python 基础风格

- 使用 Python 3.10+ 类型语法，如 `str | None`、`tuple[WorkLog, ...]`。不使用deprecated的弃用语法。
- 编译的时候使用 Python 3.11 版本进行编译，不得使用 Python 3.12+ 出现的新语法。
- 模块顶部使用 `from __future__ import annotations`。
- 使用 4 空格缩进。
- 字符串引号以双引号为主，现有代码中 SQL 多行字符串使用三引号。
- 优先使用 `pathlib.Path` 处理路径。
- 优先使用 `dataclasses.dataclass` 表达 DTO、Result、状态对象和 domain model。
- 当前项目未使用 attrs、pydantic、SQLAlchemy 或 ORM。

### 3.2 命名

- 类名：`PascalCase`，如 `WorkLogEntryViewModel`、`SQLiteWorkLogRepository`。
- 函数和方法：`snake_case`，如 `build_desktop_runtime()`、`normalize_work_log()`。
- 私有成员：前缀 `_`，如 `_view_model`、`_build_ui()`。
- 常量：`UPPER_SNAKE_CASE`，集中在 `worklogger/config/constants.py` 或模块顶部。
- DTO 命名：Command/Query 以动作或读取意图开头，如 `SaveWorkLogCommand`、`GetWorkLogQuery`。
- Use Case 命名：以 `Handler` 结尾，如 `SaveWorkLogHandler`。
- Protocol 命名：按职责命名，如 `WorkLogRepository`、`AIGateway`。
- Controller 命名：以 `Controller` 结尾；跨多个 Dialog 或文件选择/确认流程的控制器以 `WorkflowController` 结尾。

### 3.3 类型注解

- 公开函数、方法、构造函数参数和返回值应使用类型注解。
- Protocol 用于表达跨层依赖。
- Handler 返回 `Result[T]`。
- ViewModel 状态对象使用 frozen dataclass。
- Repository 方法返回 domain object、DTO、tuple 或 None，不返回裸 tuple/Row 给上层。

### 3.4 注释和 docstring

- 所有代码注释必须使用英文。
- 当前项目使用简短模块 docstring 和少量类/方法 docstring。
- 当前项目未采用 Google Style 或 Sphinx 风格的详细参数文档。
- 注释只用于解释非显而易见的约束或复杂流程，不写重复代码含义的注释。
- 公开模块、公开类和公开函数推荐至少具备一行英文总结性 docstring；复杂流程可增加简短说明，但不要写参数清单式模板文档。

### 3.5 错误返回风格

- 应用层和 ViewModel 使用 `Result.success()` / `Result.failure()`。
- 错误类型定义在 `worklogger/domain/shared/errors.py`。
- 不要让 raw infrastructure exception 穿透到 UI。
- UI 层从 `Result.error.message` 或 `AppError` 中取可显示信息。
- 若 `AppError.message` 会直接呈现给用户，创建错误时必须使用 `_()` 包裹，或传入已翻译字符串。

### 3.6 国际化字符串

- 生产代码只使用 `_()` 和 `ngettext()`。
- 不得使用 `msg()`。
- 不得使用 `MSG_DEFAULTS`。
- 不得引入 key-based translation dictionary。
- 不得在 Python 代码中硬编码非英文 UI 字符串。
- 插值格式：

```python
_("Backup saved: {path}").format(path=path)
ngettext("{count} day", "{count} days", count).format(count=count)
```

## 4. UI 开发约束

### 4.1 UI 技术

- UI 使用 PySide6 / Qt Widgets。
- 主窗口使用 `QMainWindow` 或现有 shell class。
- 对话框使用 `QDialog`。
- 可复用控件继承 Qt Widget 类。
- 当前项目未使用 QML。
- 当前项目未使用 Qt Designer `.ui` 文件。

### 4.2 UI 组织方式

- Dialog 负责构建控件、连接 signal、显示状态。
- ViewModel 负责展示状态计算和调用 Use Case，不直接依赖 Qt。
- Workflow Controller 负责打开 Dialog、注入 ViewModel、处理文件选择、确认框和跨 Dialog 流程。
- `bootstrap.py` 负责组装各 workflow controller，不在 Dialog 内部创建数据库依赖。
- Dialog 文件通常命名为 `dialog.py` 或 `dialogs.py`；Controller 文件命名为 `controller.py`。
- Controller 类必须以 `Controller` 或 `WorkflowController` 结尾。

### 4.3 布局方式

- UI 布局使用 Python 代码手写。
- 常见布局：`QVBoxLayout`、`QHBoxLayout`、`QFormLayout`、`QTabWidget`。
- SettingsDialog 使用 tabs 组织 Appearance、General、Data、Account、AI、Local Models、About。
- 控件 objectName 用于测试和样式，必须使用描述性 `snake_case`，如 `settings_dialog`、`theme_combo`、`save_report_button`。

#### 4.3.1 控件 objectName 命名规范

- 所有控件若需要设置 `objectName`，一律使用 **描述性的 `snake_case`** 格式。

- 推荐结构：`<功能/内容>_<控件类型>`，例如：
  
  - `name_line_edit`
  - `send_button`
  - `theme_combo`
  - `project_tree_view`

- 禁止使用以下过时做法：
  
  - 类型缩写前缀（如 `txtName`、`btnSend`）
  - 纯数字或无意义后缀（如 `label1`、`button2`）

- 控件类型词应使用 Qt 官方类名的下划线形式，参考列表：
  
  - `QLineEdit` → `_line_edit`
  - `QPushButton` → `_button` 
  - `QComboBox` → `_combo`
  - `QCheckBox` → `_check`
  - `QLabel` → `_label`
  - `QTableView` / `QTreeView` → `_table_view` / `_tree_view`

- 因新功能需要触及存量控件，应借机将其逐步对齐到本规范。

- 不得用 objectName 表达样式角色，例如不要用 `primary_button` 作为多个按钮的重复名称；样式角色使用动态属性，如 `setProperty("variant", "primary")`。

### 4.4 样式与主题 (QSS) 规范

#### 4.4.1 样式分离原则

- 当前项目由 `ThemeEngine` 集中生成应用级 stylesheet；不允许在 Dialog 或 Controller 中分散编写 `setStyleSheet("...")` 内联样式。
- 所有应用级样式必须存放在独立的 `.qss` 文件中，统一放置于 `presentation/theme/qss/`。
- **禁止**在任何 Dialog、Widget 或 Controller 中直接调用 `setStyleSheet()` 编写内联样式。唯一的例外见 **4.4.1.1**。
- `.qss` 文件命名采用 `<color>_<mode>.qss` 格式，例如：
  - `blue_light.qss`
  - `blue_dark.qss`
  - `custom_light.qss`
- 不按颜色创建多层子目录，避免 ThemeEngine 查找逻辑复杂化。
- **不得**使用窗口级 `setStyleSheet()` 对特定窗口覆盖全局样式。所有窗口统一使用 `QApplication.setStyleSheet()` 应用 `ThemeEngine` 加载的全局样式表。

##### 4.4.1.1 封装 Widget 的动态样式（严格限制例外）

* 只有可复用的自定义 Widget（位于 `presentation/widgets/`）可以在其内部使用 `self.setStyleSheet()` 设置**轻量、自包含**的样式。

* 该样式必须满足所有以下条件：
  
  * 只影响该 Widget 内部的子控件；
  
  * 不包含全局选择器（如 `QWidget`、`QLabel`）或会继承到外部的属性；
  
  * 不包含图片背景、复杂渐变、文件路径或用户输入拼接；
  
  * 样式内容不超过 5 行逻辑。

* 违反任一条的，必须将样式移入对应的 `.qss` 文件，并通过 `#objectName` 选择器定位。

#### 4.4.2 主题管理

- 使用 `ThemeEngine` 负责主题 palette、calendar cell 样式和应用级 stylesheet。
- `ThemeEngine` 由组合根注入到主窗口或相关 ViewModel，不在 Dialog 内部自行创建全局主题管理器。
- 支持运行时主题切换，切换时重新加载/渲染全局 stylesheet 并调用 `QApplication.setStyleSheet()`，无需重启应用。

#### 4.4.3 控件定位与选择器

- 必须使用 `#objectName` 选择器精准定位控件，避免使用层级过深的后代选择器或全局类型选择器。
- 所有被 QSS 引用的控件，其 `objectName` 必须严格遵循 `4.3.1 控件 objectName 命名规范`。
- 禁止使用全局选择器 `*`；对 `QTableView`、`QTreeView` 等高频刷新控件，不得使用 `background-image`、复杂渐变或阴影，以保证滚动流畅度。

#### 4.4.4 动态样式与伪状态

- 交互反馈（悬停、按下、禁用等）应优先使用 Qt 伪状态选择器，如 `QPushButton:hover`、`QCheckBox:checked`。
- 需要根据业务状态动态变化时，可使用动态属性选择器（例如 `QPushButton[urgent="true"] { … }`），并在 Python 代码中通过 `setProperty` 修改属性值。

#### 4.4.5 与 QPalette 的分工

- 对于仅需统一调整颜色/刷子的简单场景（如全局文本色、窗口背景），优先使用 `QPalette` 进行配置，以获得更高性能。
- QSS 仅用于需要圆角、边框、复杂状态反馈、间距、图片等 QPalette 无法实现的样式需求。

#### 4.4.6 现有代码迁移

- **现有内联样式（`setStyleSheet`）和窗口级样式**必须按以下步骤提取：
  
  1. 找出项目中所有 `setStyleSheet` 调用；
  
  2. 将其中非 Widget 封装的样式提取到对应主题的 `.qss` 文件；
  
  3. 使用 `#objectName` 定位原内联样式作用的控件，确保选择器正确；
  
  4. 删除原内联样式代码，验证界面无回退。

- **窗口级 `setStyleSheet` 必须完全移除**，由全局 QSS 接管。

- 迁移完成后，`ThemeEngine` 应完全基于 `.qss` 文件和 `QPalette` 运行，不再包含程序化样式拼接逻辑。

#### 4.4.7 一致性

- 在重命名或删除控件 `objectName` 时，必须同步检查并更新对应的 `.qss` 文件，避免样式失效。

### 4.5 Signal/Slot 约束

- 使用 PySide6 `Signal` 定义自定义信号。
- 当前项目未使用 `@Slot` / `@pyqtSlot` 装饰器作为统一规范。
- 连接方式使用 `.connect(...)`。
- 简单参数转发可使用 lambda。
- 业务动作不要直接在 Widget 中访问数据库，应转给 ViewModel 或 workflow controller。

### 4.6 可复用 Widget

当前可复用 Widget 位于 `worklogger/presentation/widgets`：

- `SwitchButton`
- `CalendarView` / calendar widgets
- `ComboChart`
- `StatsPanel`
- `WorkLogEntryPanel`

新增控件应放在 `presentation/widgets/`，并保持与现有 Widget 的手写 Qt 风格一致。

### 4.7 文案和语言

- UI 英文 msgid 写在 Python `_()` / `ngettext()` 中。
- 同步 gettext catalog 后再提交相关 UI 字符串变更。
- 非英文翻译通过 PO 文件维护，不写在 Python UI 代码中。

## 5. 数据与状态管理

### 5.1 SQLite

- 持久化数据库为 SQLite。
- 默认数据库文件名为 `worklog.db`。
- 源码运行时默认位置为 `worklogger/worklog.db`。
- frozen/PyInstaller 运行时默认位置为 executable 所在目录下的 `worklog.db`。
- 连接工厂为 `SQLiteConnectionFactory`。
- SQLite 配置：
  - `row_factory = sqlite3.Row`
  - `PRAGMA foreign_keys=ON`
  - `PRAGMA busy_timeout`
  - 文件数据库使用 WAL：`PRAGMA journal_mode=WAL`
  - 文件数据库使用 `PRAGMA synchronous=NORMAL`
- 写事务通过 `SQLiteConnectionFactory.transaction(write=True)` 串行化。
- 读操作使用短生命周期 connection。
- corrupt DB 会做 integrity check，失败时 quarantine 为 `worklog.db.bak_<timestamp>`，并按 retention 清理。

### 5.2 迁移

- 迁移由 `MigrationRunner` 执行。
- 当前初始迁移文件为 `worklogger/infrastructure/database/migrations/migration_001_initial_schema.py`。
- 迁移文件命名规范`migration_<NNN>_<description>.py`。
- 迁移必须幂等。
- 新迁移文件不得含 `v4` 命名。

### 5.3 Repository

- Repository Protocol 位于 domain 层。
- SQLite 实现位于 infrastructure 层。
- Repository 方法负责 row mapping。
- 上层只能看到 domain object 或 DTO。
- per-user 数据必须带 `user_id` 过滤或唯一约束。

### 5.4 配置与设置

- 稳定配置键集中在 `worklogger/config/constants.py`。
- 用户设置存储在 SQLite settings repository 中。
- 当前项目未使用 QSettings。
- 当前项目未使用 YAML/INI 作为主配置。
- Identity provider 本地配置文件存在于 `worklogger/infrastructure/identity/config.py` 相关流程；`.gitignore` 忽略 `worklogger/config/identity.local.json` 和 `identity.*.local.json`。
- Local model catalog/manifest 使用 JSON 文件，位于运行目录的 `models/` 下。

### 5.5 全局状态

- 当前语言状态由 `worklogger.infrastructure.i18n` 内部 RLock 保护。
- Qt application 和窗口由 `DesktopRuntime` 持有。
- 当前登录用户由 runtime/session 对象传入 ViewModel。
- 不使用全局 service locator 访问业务服务。
- 依赖组装集中在 `bootstrap.py`。

### 5.6 安全状态

- 密码使用 PBKDF2 hasher。
- remember token 存储为 SHA-256 digest，不存明文 token。
- remember-session 本地存储由 `FileRememberTokenSessionStore` 管理。
- secret/key storage 使用 keyring 优先和 encrypted fallback。
- OAuth identity 不保存 access token、refresh token、ID token、auth code 或 PKCE verifier。

### 5.7 安全实现约束

- SQLite 操作必须使用参数化查询，例如 `execute("... WHERE id=?", (value,))`；严禁用 f-string、`format()` 或字符串拼接把用户输入拼入 SQL。
- SQLite `PRAGMA` 语句不总是支持参数绑定；这类语句只允许使用经过类型转换和范围校验的内部数值，不得包含用户输入。
- Application 层 Command DTO 负责基础输入校验，如必填、长度、格式和范围；领域层负责业务规则校验；UI 层只做展示性校验，如 `QValidator` 或禁用按钮。
- 不允许让未经校验的用户输入直接穿透到 Use Case 或 Repository。
- 如果 `QTextBrowser`、富文本 label 或 AI 对话框渲染外部/模型生成内容，必须按纯文本或受限 HTML 渲染；禁止加载远程图片、远程样式、脚本或执行任何动态内容。
- 日志、异常、审计和导出文件不得包含密码、remember token、OAuth token、API key、PKCE verifier 或用户未授权公开的明文输入。

### 5.8 依赖注入与组合根演进

- `bootstrap.py` 是组合根，负责显式创建 Repository、Use Case、ViewModel、Controller 和 Window。
- 组合根文件可以因显式依赖组装而偏长；判断是否需要拆分时以函数复杂度、功能边界和可测试性为准，不使用机械行数阈值。
- 当单个组装函数跨多个功能域、难以测试，或出现重复创建逻辑时，应拆分为 `bootstrap_<feature>.py` 私有组装模块，由 `bootstrap.py` 保持顶层编排。
- 所有组装函数必须显式返回组装好的对象，如 Controller、Window 或 runtime dataclass；不得在函数内部挂载到全局变量。
- `container.py` 只作为轻量键值容器，不承载创建逻辑，不替代组合根。
- 新引入的 Repository、Gateway、Service 必须在组合根中显式创建并通过构造函数注入；Dialog 和 Controller 不得通过 `container.resolve()` 私自获取业务依赖。

## 6. 错误处理与日志

### 6.1 错误类型

统一错误类型：

- `AppError`
- `ValidationError`
- `AuthenticationError`
- `AuthorizationError`
- `NotFoundError`
- `ConflictError`
- `InfrastructureError`
- `CancellationError`

### 6.2 错误处理边界

- Domain 规则可以抛出 `TypeError` / `ValueError`，Application Handler 捕获后转换为 `ValidationError`。
- Runtime composition 捕获启动异常并转换为 `InfrastructureError("desktop_runtime_failed", ...)`。
- UI 读取 `Result` 并显示错误，不处理 raw sqlite/network exception。
- Backup、restore、AI、download、identity 等 adapter 错误应转换为 structured error。

### 6.3 日志

- 发布前必须建立统一 `logging` 配置，例如 `worklogger.infrastructure.logging.setup_logging()`，并由 `bootstrap.py` 或入口启动流程调用一次。
- 日志格式必须包含时间、模块名、级别和消息；日志消息不得包含 PII、密码、token、API key 或用户明文敏感输入。
- 日志级别约定：
  - `DEBUG`：开发诊断信息，只在开发模式或显式启用时输出。
  - `INFO`：关键流程节点，如启动、登录成功、主题切换、导入导出完成、备份完成。
  - `WARNING`：可恢复降级，如备用字体加载失败、可重试网络失败、可忽略的外部服务不可用。
  - `ERROR`：捕获异常后记录完整 traceback，并附带足以定位问题的上下文。
- frozen/PyInstaller 模式下日志文件写到可执行文件同级目录的 `worklogger.log`；源码运行模式下日志路径必须显式定义，且日志文件继续由 `.gitignore` 忽略。
- 文件日志应使用轮转策略，例如 `RotatingFileHandler`，默认保留 5 个备份、单文件 1 MB。
- 所有被捕获的 `InfrastructureError` 和 `AppError` 若会导致流程失败，必须记录 error log；UI 仍只显示结构化错误消息。

## 7. 线程与异步约束

### 7.1 当前已定义的抽象

- `worklogger.app.job_runner.CancellationToken` 使用 `threading.Event`。
- `JobRunner` 是 Protocol，提供 `submit(name, job, on_complete=None)`。
- `JobHandle` 暴露 `job_id` 和 `cancel`。
- AI 和长任务相关 use case 支持 cooperative cancellation 的接口或检查。

### 7.2 当前 UI 中已使用的计时机制

- `WorkLogEntryPanel` 使用 `QTimer` 支持自动记录相关 UI 刷新。
- 当前项目未把所有耗时操作统一接入 QThread。

### 7.3 当前未定义或未使用

- 当前项目未使用 asyncio-first 架构。
- 当前项目通过 `QtJobRunner` 使用 Qt thread pool 执行耗时任务。
- 当前项目通过 Qt signal 将 `JobRunner` 完成结果派发回 UI 线程。
- 当前项目不采用 asyncio-first 架构，也不把 `concurrent.futures` 作为表现层统一规范。
- 新增耗时入口必须继续接入 `JobRunner`，不能回退到 UI 线程同步执行。

当前需要优先接入 `JobRunner` 或等价 worker 的 handler：

| Handler                           | 风险                  |
| --------------------------------- | ------------------- |
| `DownloadLocalModelHandler`       | 文件下载会阻塞 UI          |
| `RefreshLocalModelCatalogHandler` | 网络请求会阻塞 UI          |
| `CheckForUpdatesHandler`          | GitHub API 调用会阻塞 UI |
| `AiChatHandler`                   | AI 推理/网络请求会阻塞 UI    |
| `VerifyLocalModelHandler`         | 大文件哈希校验会阻塞 UI       |

### 7.4 必须遵守的边界

- 新增长耗时操作必须通过应用层 port 或明确的 workflow/controller 边界接入。
- 不要在 domain 层引入线程或 Qt。
- 不要在 UI 线程中执行网络下载、本地模型推理、长时间 AI 请求或大文件处理。
- 如果现有 worker 不能覆盖新的任务类型，实现前应先补充与 `JobRunner` contract 一致的 runner 能力和测试。

### 7.5 性能与资源约束

- UI 线程中的同步操作应保持在用户不可感知范围内；任何可能超过 100 ms 的网络、磁盘、模型、压缩、哈希或大文件处理必须走 `JobRunner`，并显示进度、忙碌状态或可取消入口。
- 数据库读操作使用短生命周期连接，使用后立即关闭；写操作通过事务上下文管理器，保证自动提交或回滚。
- QSS 应避免深层嵌套选择器；单个 QSS 文件如被引入，不应超过 100 KB；对 `QTableView`、`QTreeView` 等高频刷新控件禁止复杂渐变、图片背景和阴影。
- 本地模型推理不得把大型模型文件完整读入 UI 进程内存；优先使用独立进程、内存映射或底层 runtime 的流式加载机制。
- 大型导入导出、备份恢复和模型下载必须提供失败恢复或用户可理解的错误状态。

## 8. 打包与部署约束

### 8.1 当前状态

- 项目目标打包工具是 PyInstaller。
- 当前工作树中尚未看到 PyInstaller spec、Windows/macOS/Linux build scripts 或 `.github/workflows`。

### 8.2 入口和 smoke

- 打包入口应使用 `worklogger/main.py` 或模块入口 `worklogger.main`。
- 必须保留：
  - `--smoke-import`
  - `--smoke-runtime`
  - `--smoke-startup`
  - `--help`
- 无参数启动桌面应用。
- packaged smoke 应覆盖 import、runtime startup、locale/assets 加载。

### 8.3 资源

PyInstaller 配置需要包含：

- `worklogger/assets/icons`
- `worklogger/assets/fonts`
- `worklogger/assets/images`
- `worklogger/locales`
- `model_catalog.json`
- 必要 hidden imports：AI、identity、local model、templates、export、calendar、i18n、presentation modules。

### 8.4 依赖

项目材料定义的核心依赖：

- `PySide6`
- `tzlocal`
- `holidays`
- `cryptography`
- `keyring`
- `certifi`
- `PyJWT>=2.8.0`
- `llama-cpp-python>=0.3.19`
- `httpx>=0.27.0`
- `portalocker>=2.8.0`

### 8.5 打包输出

当前项目尚未定义最终 artifact 命名规则。

文档材料要求覆盖：

1. PyInstaller spec finalization。
2. Windows/macOS/Linux build scripts。
3. GitHub Actions release workflow。
4. Artifact naming and release upload。
5. Code signing/notarization preparation。
6. Packaged smoke tests。
7. README/CHANGELOG release packaging text。

## 9. 版本控制与协作约定

### 9.1 分支

- 当前开发分支预期为 `dev-v4`。
- 不创建 `v4-main`。
- 不在实现、runtime artifact、workflow、DB、config key、class/function/package/resource path 中使用 `v4` 或 `V4` 命名。

### 9.2 Git 忽略规则

`.gitignore` 当前忽略：

- Python cache：`__pycache__/`、`*.py[cod]`。
- 虚拟环境：`venv/`、`.venv/` 等。
- PyInstaller/build 输出：`build/`、`dist/`、`release/`、`*.exe`、`*.dmg`、`*.app`、archives。
- 日志：`*.log`、`worklogger.log`。
- 本地 DB：`worklog.db`、`*.db`、`*.bak_*`、WAL/SHM。
- 本地配置：`worklogger/config/*.json`、identity local json。
- 自定义模板 runtime json。
- gettext 编译产物 `.mo`。
- 测试 artifact。
- 本地模型 `.gguf`、download temp、catalog、lock、manifest。
- `docs/refactor/*.md`。

注意：真实测试文件必须可追踪，不能被 ignore。

### 9.3 测试约定

测试按层组织：

```text
tests/app
tests/architecture
tests/domain
tests/i18n
tests/infrastructure
tests/presentation
```

测试文件按功能命名，不按 phase 命名。

测试函数命名使用 `test_<what>_<expected_behavior>`，例如 `test_save_work_log_should_persist_to_db`。

不要求硬性覆盖率数字，但以下测试必须存在：

1. 架构测试：新增或修改层边界、命名规则、入口约束时，必须在 `tests/architecture` 增加或更新守卫测试。
2. 领域规则测试：纯函数和领域规则必须用无 mock 的测试覆盖关键分支。
3. Repository 集成测试：SQLite Repository 必须使用 `:memory:` 或临时文件数据库验证迁移、CRUD、事务和 row mapping 行为。
4. Presentation smoke/行为测试：新增 Dialog、Controller 或 Widget 时，至少覆盖 offscreen 创建、核心信号和 ViewModel 绑定。

Mock 使用限制：

- Domain 测试禁止 mock 领域对象。
- App 层测试可以 mock Repository Protocol 或 Gateway Protocol。
- Infrastructure 测试优先使用真实临时资源，只有外部网络、keyring、系统服务可以替换为 fake。
- Presentation 测试可以使用 fake ViewModel 或 handler，但不得绕过控件的公开交互接口直接改内部状态。

当前验证命令：

```powershell
python -m unittest discover
python -m pytest -q
python scripts\i18n\i18n_check.py
python worklogger/main.py --smoke-import
$env:QT_QPA_PLATFORM='offscreen'; python worklogger/main.py --smoke-startup
```

`i18n_check.py` 必须持续检查 POT/PO/MO 的一致性；后续增强应覆盖所有 `_()` / `ngettext()` 调用是否存在于 POT。

### 9.4 GitHub / CI

- 当前项目材料要求实现 GitHub Actions release workflow。
- 当前工作树未发现 `.github/workflows`。未来将补充。
- 当前项目未定义提交信息格式。未来将补充。
- 当前项目未定义 PR 模板。未来将补充。

## 10. 后续 AI 开发硬性约束摘要

后续 AI 修改代码时必须遵守：

- 不引入 `v4` / `V4` 到实现或 runtime 命名。
- 不跨越四层架构边界。
- Domain 不导入 UI、SQLite、infrastructure。
- App 不导入 Qt Widgets，不直接使用 sqlite3。
- Presentation 不直接使用 sqlite3。
- Infrastructure 负责技术实现和 row mapping。
- 新业务入口优先增加 Command/Query DTO 和 Use Case Handler。
- 新 UI 先增加或扩展 ViewModel，再接 Dialog/Controller。
- 所有 UI 字符串使用 `_()` / `ngettext()`。
- 所有代码注释使用英文。
- 公开类/函数推荐具备英文总结性 docstring。
- 不引入 SQLAlchemy、ORM、web frontend、QML、Tauri 或 asyncio-first 架构。
- 不引入未在当前项目使用或需求材料明确允许的库。
- SQLite 查询必须参数化，禁止拼接用户输入。
- 耗时任务必须走 `JobRunner` 或等价 worker，不阻塞 UI 线程。
- `bootstrap.py` 只做顶层组装，单个组装函数膨胀后按功能拆分私有组装模块。
- 发布前必须补齐打包 smoke，并保持统一 logging 与 `JobRunner` 覆盖耗时 UI 入口。
- 修改 i18n 字符串后运行 extract/sync/compile/check。
- 修改架构边界后运行 architecture tests。
- 修改运行入口后运行 smoke import 和 smoke startup。
- 新功能必须有对应 domain/app/infrastructure/presentation 层级合适的测试或明确 manual smoke 记录。
