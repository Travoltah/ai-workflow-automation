-- Edge-case tests for rules whose logic is easy to get wrong. Runs inside a transaction that is
-- rolled back, so the data is untouched. Raises an error (non-zero psql exit) when a case fails.
-- Run on CLEAN data:  psql -d contoso_dq -v ON_ERROR_STOP=1 -f evaluation/rule-edge-cases.sql
--
-- Why these exist: in the first live run, Claude's explanation of TXN_VOLUME_DROP pointed out that
-- the rule compared the latest date in the data, which in production is today's partial day.
-- The rule was fixed to use yesterday (complete UTC day), and to count a day with no rows as 0.

\o /dev/null
BEGIN;

CREATE FUNCTION pg_temp.violations(p_rule text) RETURNS int LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
  EXECUTE 'SELECT count(*) FROM (' || (SELECT check_sql FROM dq.rules WHERE rule_code = p_rule) || ') x' INTO n;
  RETURN n;
END $$;

CREATE FUNCTION pg_temp.expect(p_case text, p_got int, p_want int) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  IF p_got <> p_want THEN RAISE EXCEPTION 'FAIL %: got % violation(s), expected %', p_case, p_got, p_want; END IF;
  RAISE NOTICE 'PASS %', p_case;
END $$;

-- TXN_VOLUME_DROP
SELECT pg_temp.expect('volume: clean data', pg_temp.violations('TXN_VOLUME_DROP'), 0);
INSERT INTO wallet.transactions
SELECT 99000000 + g, 50001, 'deposit', 10, 0, 'completed', 'EDGE-TODAY-' || g, greatest(current_date::timestamptz, now() - interval '1 minute' * g)
  FROM generate_series(1, 40) g;
SELECT pg_temp.expect('volume: a partial current day is ignored', pg_temp.violations('TXN_VOLUME_DROP'), 0);
DELETE FROM wallet.transactions WHERE created_at >= current_date - 1 AND created_at < current_date;
SELECT pg_temp.expect('volume: a day with zero transactions is caught', pg_temp.violations('TXN_VOLUME_DROP'), 1);

-- TXN_WITHDRAWAL_FEE: boundaries of the fee rule (1.5%, min 0.25, max 15.00, half-up rounding)
INSERT INTO wallet.transactions (txn_id, wallet_id, txn_type, amount, fee, status, external_ref, created_at) VALUES
  (99100001, 50001, 'withdrawal',   16.67,  0.25, 'completed', 'EDGE-FEE-1', now() - interval '3 days'),  -- 0.25005 -> 0.25
  (99100002, 50001, 'withdrawal', 1000.00, 15.00, 'completed', 'EDGE-FEE-2', now() - interval '3 days'),  -- exactly the cap
  (99100003, 50001, 'withdrawal',   33.33,  0.50, 'completed', 'EDGE-FEE-3', now() - interval '3 days'),  -- 0.49995 -> 0.50
  (99100004, 50001, 'withdrawal',    1.00,  0.25, 'completed', 'EDGE-FEE-4', now() - interval '3 days');  -- minimum
SELECT pg_temp.expect('fee: correct boundary fees pass', pg_temp.violations('TXN_WITHDRAWAL_FEE'), 0);
UPDATE wallet.transactions SET fee = 0.49 WHERE txn_id = 99100003;
SELECT pg_temp.expect('fee: truncation instead of rounding is caught', pg_temp.violations('TXN_WITHDRAWAL_FEE'), 1);

-- CUST_EMAIL_DUPLICATE: differs only by case
UPDATE wallet.customers SET email = upper((SELECT email FROM wallet.customers WHERE customer_id = 1001)) WHERE customer_id = 1002;
SELECT pg_temp.expect('email: duplicate in a different case is caught', pg_temp.violations('CUST_EMAIL_DUPLICATE'), 1);

ROLLBACK;
