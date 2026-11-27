# 外接监听器返听与交席

只为一个指定席位接入一台独立监听器。节目发行、装载、名册资格和返听样值沿用 README.md 的约定。新办返听按受理时的实际使用人和指定的装载件取值。席端重开时继续连同一台设备。设备库和席库分开。由环回 HTTP 交接。本题使用夹具代替实体硬件。

## 设备接口

| 调用 | 约定 |
| --- | --- |
| GET /state | 200 返回 {"number":0,"last":null} 或当前操作号及末笔。末笔字段为 operation、kind、sample。 |
| POST /operate | 提交 {"expected":0,"operation":"唯一操作标识","kind":"sound","sample":25}。kind 为 advance 时不带 sample，也不会出声。 |

expected 是提交所依据的当前设备号。匹配时设备原子地执行该操作、推进一号并返回与 /state 同形的末笔。sound 实出一帧整数样值，范围 −127 至 127。advance 的末笔 sample 为 null。预期号不匹配时返回 409，设备保持原状。重投同一命令仍用原操作标识、预期号和样值。晚到的命令仍按到达时的当前号处理。设备可能在实际提交后断开连接，也可能暂时不可达。设备接口只能查末笔，不能查历史。监听器由绑定席位独用，测试可延迟送达已发出的命令。

## 席端接口

沿用席端模块和原 HTTP 路径。通过启动选项 --device-seat 和 --device-port 指定绑定席及环回设备端口。自动化可用原 serve_monitor 工厂传入同义的关键字参数 device_seat 和 device_port。省略时使用原席端行为。以下响应适用于绑定席。

- POST /listen_frame 沿用 seat、edition、frame、request。HTTP 200 的实听含原首执字段，另含 status 为 played 及 device_number。截停的 200 含 seat、edition、frame、request、status（stopped），没有实听首执或实听序号。
- POST /handover 收 seat、operator、request。沿用最近装载件的名册资格。HTTP 200 含 seat、operator、edition、request、status（completed），并确认新使用人可以开始返听。旧声若在交席前已实出，仍按当时人员核回。尚未出声时，允许在交席前结清，也允许经设备截停。仅查到当前没有旧声，不能确认迟到命令已失去出声资格。
- 受理后仍待核时，POST 返回 202，至少含 seat、request、status（pending）。整个席位只可有一笔已受理且待核的设备返听。若有其他业务在办而本次尚未受理，可返回 202 和 status（busy），以原号重试即可。设备可用、原操作可送达且无新请求争用时，续办可得到终局。
- 两个 POST 各按本席的请求号识别原业务。同号同参可续办或原样复领，已受理请求异参返回 409。GET /receipt 仍收 seat、request，仅查返听在席库已记下的结果。已有实听或截停返回 200，已受理待核返回 202，未知请求返回 404。重开后按原号查询和续办。既有 V1 首执按原样返回。

## 联排样例

用已有录音接口给 rehearsal 的原帧 101 提交 m1 为 −15、m3 为 25，沿用开台时 m1 归 a、m3 归 b。校样并冻结 [101]，装入 booth，关闭发行端。第 1 帧的节目声为 10，甲 a 的返听为 25，乙 b 为 −15。可用 request 为 initial 的交席请求先交给甲。所有实听的原录出处均应对应录音接口返回的 101 原据。

设备夹具在 tests/test_listener_device.py。用 tests.support.HttpService 启动 serve_device，传入独立数据库和 controls=DeviceControls()。端口取 device.server.server_address[1]。defer_next_sound() 让下一笔 sound 暂不送达设备并向调用方返回 503。用 take_deferred() 取得延迟命令，之后可按原样再次投递。drop_next_commit() 让下一笔实际提交的操作丢掉 HTTP 回包。两种故障触发后都暂时让设备查询和提交返回 503，直至调用 set_unavailable(False)。也可直接用 set_unavailable(True) 暂停设备。sounds() 给出夹具观察到的出声，供断言和演示使用。席端只能使用上表的两个设备入口。

- 延迟甲的 q，恢复设备应答后办理交席给乙。交席报成功后再送达迟到命令，不新增甲的 25。旧 q 只可复领交席前的首执或截停结果。乙用新号实出 −15。
- 甲的 q 实出 25 后丢掉设备回包。重开席端并恢复设备应答，交给乙，再办乙的新号。末笔被乙覆盖后，q 仍可查回原设备操作号、甲、25 和原据。两个实听都只出声一次。
- 设备不可核实时，交席报待核，查单不触发出声。另一次返听不得覆盖未核回的设备证据。设备恢复后按原号续办并检查同号改参。普通席继续走原回归。

原运行清单的核验入口执行完整回归，保留失败退出码。将新席的交接场景纳入核验，把实际出声次序、交席状态及原号核回接进演示。
