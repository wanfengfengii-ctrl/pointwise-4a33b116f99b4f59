# 榆桥广播剧联排服务

榆桥社区广播剧小组用录音发行端保存原录、制作校样和发行节目。值班员用独立的返听端在发行端停机后继续交班。录音员可以在同一帧录入同一发言人的两支话筒，混音员能按冻结件回听节目，返听值班员能按实听号核对交班前后的结果。

## 运行

需要 Python 3.11，依赖均来自标准库。完整回归由项目检查入口运行。

```sh
python3 -B check_project.py
```

演示使用 `samples/rehearsal.json` 和临时数据库，启动实际环回 HTTP 服务，装载后关闭发行端，最后用同一席库重开返听端。

```sh
python3 -B -m tests.test_workflow
```

手动运行时在两个终端各启动一端。

```sh
python3 -B -m studio.source_service --db source.sqlite --port 8001
python3 -B -m monitor.listen_service --db monitor.sqlite --port 8002
```

## 接口

服务绑定 `127.0.0.1`。POST 请求使用 `Content-Type: application/json` 和 JSON 对象，请求字段见下表。GET 经查询参数提供字段。成功的业务响应使用 HTTP 200。件号、原帧号和节目帧位置为正整数。节目帧位置从 1 起。

| 服务与方法 | 路径 | 输入和结果 |
| --- | --- | --- |
| 录音 `POST` | `/configure` | `program`，可选 `speakers`（人员号到姓名）和 `assignments`（话筒号到人员号）。成功返回名册和当前全部分配。省略两组数据可查配置。 |
| 录音 `POST` | `/record_frame` | `program`、`source_frame`、`contributions`（话筒号到整数样值）。返回 `origin` 和按话筒号排序的 `contributions`，每项带 `microphone`、`speaker`、`sample`。 |
| 录音 `GET` | `/record_frame` | `program`、`source_frame`。读回该次原录。 |
| 混音 `POST` | `/preview` | `program`、`revision`、有序 `source_frames`。返回 `freezable`、带位置及出处的 `frames`、缺失位置 `missing`。可重复引用同一原帧。 |
| 发行 `POST` | `/freeze` | `program`、`revision`。返回 `edition` 和可供装载的 `package`。每次成功取得新件号。 |
| 发行 `GET` | `/program_audio` | `edition`、`frame`。返回指定件的 `sample` 和 `origin`。 |
| 席端 `POST` | `/load` | `seat`、完整 `package`。返回装载的 `edition`、`seat` 和 `revision`。 |
| 席端 `POST` | `/handover` | `seat`、`operator`。按该席最近一次成功装载件的固定名册办理。 |
| 席端 `POST` | `/listen_frame` | `seat`、`edition`、`frame`、`request`。返回件号、节目帧位置、请求号、席位、实际 `operator`、`sample`、`sequence` 和 `origin`。 |
| 席端 `GET` | `/receipt` | `seat`、`request`。领取实际实听的同一份结果。 |

`origin` 含 `program`、`source_frame` 和 `recording_receipt`。席端按席位和件号保存已装载件，办理返听时使用请求显式指定的件。交班后如果指定旧件的固定名册没有当前使用人，该次首次实听拒绝。

错误响应包含字符串 `error` 和适用的字段。非法输入、未知分配人员、无有效分配和坏件为 400。未知节目、原帧、修订、件、节目帧和首执为 404。已受理位置、已登记人员变更姓名、同修订异序、冻结不可发行的修订、同件号冲突、未分配席位和实听同号异参为 409。校样即使发现缺帧仍返回校样结果和缺失位置。补录后可按原修订号和原顺序重新校样。变更编排使用新修订号。

## 一天的联排

1. 录音发行端开台并补齐 `rehearsal`、甲 `a`、乙 `b` 和 `m1` 至 `m3`。重复开台补齐缺项，保留后来有效改配及历史。静默帧也由录音员明确提交。
2. 录音员把 `m2` 改给甲，与 `m1` 同时使用。乙使用 `m3`。原帧 101 提交 `80、10、60`，另外提交一帧反号声音和一帧空贡献。
3. 录音员把 `m2` 改回乙。查回原帧 101 时 `m2` 仍归甲。一次录入的帧头、逐路样值、原归属和原录收据同时提交。
4. 混音员按 `[101, 102, 103]` 校样，得到 `[127, -127, 0]`。样值以一帧内的整数计，先精确求和，再限幅到闭区间 `[−127, 127]`。空贡献总和为零。`null`、布尔值和非整数样值被拒绝。
5. 发行员冻结校样。每个节目位置含固定出处和节目声。冻结件随附该版名册每人的返听声，按原录归属排除属于此人的全部贡献后对余项求和、限幅。名册中当帧无贡献的人听到节目声。
6. 席端核验 V1 装载件的名册、连续帧位、出处对应、样值范围和返听覆盖后，保存本地副本。坏件拒绝时保留原有效装载。装载成功后可以关停录音发行端。
7. 值班员把 `booth` 交给甲。指定件第一帧的节目声为 127，甲实际返听 60。席端事务提交即代表一次出声，同次保存实听首执。
8. 值班员可在失答后把席位交给乙并重开席端。同号同件同帧或查单领回甲的 60、原序号和出处。乙以新号得到 90。同号异参拒绝，未装载件和不存在的帧均不生成实听。
