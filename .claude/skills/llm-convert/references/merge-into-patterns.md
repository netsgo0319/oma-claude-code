# MERGE INTO → INSERT ... ON CONFLICT 변환 패턴

## 기본 UPSERT

```sql
-- Oracle
MERGE INTO users t
USING (SELECT #{id} AS id, #{name} AS name, #{email} AS email FROM DUAL) s
ON (t.id = s.id)
WHEN MATCHED THEN
  UPDATE SET t.name = s.name, t.email = s.email
WHEN NOT MATCHED THEN
  INSERT (id, name, email) VALUES (s.id, s.name, s.email)

-- PostgreSQL
INSERT INTO users (id, name, email)
VALUES (#{id}, #{name}, #{email})
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name, email = EXCLUDED.email
```

## 조건부 UPDATE

```sql
-- Oracle
MERGE INTO users t
USING new_data s ON (t.id = s.id)
WHEN MATCHED THEN
  UPDATE SET t.name = s.name
  WHERE t.updated_at < s.updated_at  -- 조건부 UPDATE
WHEN NOT MATCHED THEN
  INSERT (id, name) VALUES (s.id, s.name)

-- PostgreSQL
INSERT INTO users (id, name, updated_at)
SELECT id, name, updated_at FROM new_data
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name
WHERE users.updated_at < EXCLUDED.updated_at
```

## DELETE 절 포함

```sql
-- Oracle
MERGE INTO users t
USING new_data s ON (t.id = s.id)
WHEN MATCHED THEN
  UPDATE SET t.name = s.name
  DELETE WHERE t.status = 'DELETED'

-- PostgreSQL (2단계로 분리)
-- Step 1: UPSERT
INSERT INTO users (id, name, status)
SELECT id, name, status FROM new_data
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name;

-- Step 2: DELETE
DELETE FROM users WHERE status = 'DELETED'
AND id IN (SELECT id FROM new_data);
```
> MERGE의 DELETE 절은 ON CONFLICT에서 직접 지원하지 않으므로 분리 실행 필요.
> 트랜잭션 내에서 두 문장을 함께 실행하도록 안내.

## 복합 JOIN 조건

```sql
-- Oracle
MERGE INTO order_items t
USING new_items s ON (t.order_id = s.order_id AND t.item_id = s.item_id)
...

-- PostgreSQL (복합 UNIQUE 제약 필요)
INSERT INTO order_items (order_id, item_id, qty)
VALUES (#{orderId}, #{itemId}, #{qty})
ON CONFLICT (order_id, item_id) DO UPDATE
SET qty = EXCLUDED.qty
```
> ON CONFLICT에는 UNIQUE 인덱스 또는 제약이 필수.
> 대상 테이블에 적절한 UNIQUE 제약이 없으면 migration-guide.md에 기록.
