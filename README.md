# Borrowboard · 邻里借用

上架 → 借出通过 → 归还；单物件同时仅一笔在借，含逾期判定。

应还截止 = 应还日 + 可选截止钟点（`due_time`，HH:MM 24 小时制）：

- 借出通过可带当天的时分；没写钟点的老笔按应还日 00:00 计。
- 只过了应还日、还没到钟点的笔不算逾期——逾期扫名单（`classify_loans`）、
  在借栏样式、顶细条计数、归还是否计为逾期笔，全部走 `is_overdue` 同一结论；
  归还瞬间的结论写入 `was_overdue` 钉死。
- 钟点严格校验：25 点、缺分钟等非法值整单失败（400），不落任何库。
- 宽限 `POST /api/loans/{id}/grace {"days":N}` 只加自然日，钟点原样保留。
- 顺延 `POST /api/loans/{id}/extend {"days":N,"time_policy":"follow|keep"}`：
  `follow` 时分跟着新日走，`keep` 钉在原时刻整体平移；分栏与顶细条共用。

| 服务 | 端口 |
| --- | --- |
| 前端 | 5400 |
| API | 10400 |

0-1：`deposit` / `damage_note` / `neighbor_rating`。
