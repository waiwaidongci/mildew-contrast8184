# 002 外站交接与规则版本

应用启动时以 SQLAlchemy 模型补建缺失表，不改写已存在的表与约束。

- `runs.rule_version` 记录每次运行使用的已发布规则版本。新列默认取当前版本，
  旧行按字段默认值补齐。已有库须显式执行以下迁移（默认 `r1`）：

  ```sql
  ALTER TABLE runs ADD COLUMN rule_version VARCHAR(20) NOT NULL DEFAULT 'r1';
  ```
- `handoff_batches` 保存外站交接包携带的原巡检，`batch_key` 唯一，`checksum` 唯一，
  保证相同巡检批次只存一份。
- `handoff_reports` 以 `(station, report_no)` 唯一，各站同号报告各自保留；
  同站同号但内容变化时按冲突退回，不写入新行。
- 报告的状态只会是验算通过的 `verified`；验算不一致的交接包不写入批次与报告，
  仅在 `audit_events` 留退回记录。
