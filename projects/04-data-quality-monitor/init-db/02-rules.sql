-- The data quality rules. Each check_sql returns one row per violation: record_id (text) and detail (text).
-- Rules are data: add, change or switch one off with an INSERT or UPDATE, no workflow change needed.

\connect contoso_dq

INSERT INTO dq.rules (rule_code, rule_name, dimension, table_name, severity, owner, description, check_sql) VALUES

('CUST_EMAIL_MISSING', 'Customer email is missing', 'completeness', 'wallet.customers', 'medium', 'Customer data team',
 'Every customer needs an email address for receipts, password resets and security alerts.',
 $q$SELECT customer_id::text, 'customer ' || customer_id || ' has no email (value is ' ||
           CASE WHEN email IS NULL THEN 'NULL' WHEN email = '' THEN 'an empty string' ELSE 'only spaces' END || ')'
      FROM wallet.customers WHERE email IS NULL OR btrim(email) = ''$q$),

('CUST_EMAIL_FORMAT', 'Customer email is not a valid address', 'validity', 'wallet.customers', 'medium', 'Customer data team',
 'Emails must look like name@domain.tld, or messages bounce.',
 $q$SELECT customer_id::text, 'email "' || email || '"'
      FROM wallet.customers
     WHERE email IS NOT NULL AND btrim(email) <> '' AND email !~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'$q$),

('CUST_EMAIL_DUPLICATE', 'Two customers share one email', 'uniqueness', 'wallet.customers', 'high', 'Customer data team',
 'An email identifies one customer. A shared email can send one customer''s alerts to another.',
 $q$SELECT lower(email), 'used by customers ' || string_agg(customer_id::text, ', ' ORDER BY customer_id)
      FROM wallet.customers WHERE email IS NOT NULL AND btrim(email) <> ''
     GROUP BY lower(email) HAVING count(*) > 1$q$),

('CUST_KYC_STATUS', 'KYC status is not an allowed value', 'validity', 'wallet.customers', 'high', 'Compliance',
 'KYC status must be verified, pending or rejected; anything else breaks transaction limits and reporting.',
 $q$SELECT customer_id::text, 'kyc_status "' || coalesce(kyc_status, 'NULL') || '"'
      FROM wallet.customers WHERE kyc_status IS NULL OR kyc_status NOT IN ('verified', 'pending', 'rejected')$q$),

('WALLET_ORPHAN', 'Wallet belongs to no customer', 'integrity', 'wallet.wallets', 'critical', 'Core wallet team',
 'Every wallet must belong to an existing customer; an orphan wallet can''t be reconciled or reported to the regulator.',
 $q$SELECT w.wallet_id::text, 'customer_id ' || coalesce(w.customer_id::text, 'NULL') || ' does not exist'
      FROM wallet.wallets w LEFT JOIN wallet.customers c ON c.customer_id = w.customer_id
     WHERE c.customer_id IS NULL$q$),

('WALLET_NEGATIVE_BALANCE', 'Wallet balance is negative', 'validity', 'wallet.wallets', 'critical', 'Finance',
 'Wallets have no overdraft, so a balance below zero means money left that the wallet didn''t have.',
 $q$SELECT wallet_id::text, 'balance ' || balance FROM wallet.wallets WHERE balance < 0$q$),

('WALLET_CURRENCY', 'Wallet currency is not supported', 'validity', 'wallet.wallets', 'medium', 'Core wallet team',
 'Wallets hold USD, ZWG or ZAR, as ISO 4217 codes.',
 $q$SELECT wallet_id::text, 'currency "' || coalesce(currency, 'NULL') || '"'
      FROM wallet.wallets WHERE currency IS NULL OR currency NOT IN ('USD', 'ZWG', 'ZAR')$q$),

('TXN_DUPLICATE_REF', 'Payment reference used more than once', 'uniqueness', 'wallet.transactions', 'critical', 'Payments operations',
 'Each external reference from the payment switch must appear once; a repeat usually means a payment was posted twice.',
 $q$SELECT external_ref, count(*) || ' transactions: ' || string_agg(txn_id::text, ', ' ORDER BY txn_id)
      FROM wallet.transactions GROUP BY external_ref HAVING count(*) > 1$q$),

('TXN_AMOUNT_RANGE', 'Transaction amount out of range', 'validity', 'wallet.transactions', 'high', 'Payments operations',
 'Amounts must be above zero and at most 10,000.00 per transaction.',
 $q$SELECT txn_id::text, txn_type || ' of ' || amount FROM wallet.transactions WHERE amount <= 0 OR amount > 10000$q$),

('TXN_FUTURE_DATE', 'Transaction dated in the future', 'validity', 'wallet.transactions', 'high', 'Payments operations',
 'A transaction can''t happen after the moment it is loaded; future dates usually mean a time-zone or clock error.',
 $q$SELECT txn_id::text, 'created_at ' || created_at FROM wallet.transactions WHERE created_at > now() + interval '5 minutes'$q$),

('TXN_ORPHAN_WALLET', 'Transaction on a wallet that does not exist', 'integrity', 'wallet.transactions', 'critical', 'Payments operations',
 'Every transaction must belong to an existing wallet.',
 $q$SELECT t.txn_id::text, 'wallet_id ' || coalesce(t.wallet_id::text, 'NULL') || ' does not exist'
      FROM wallet.transactions t LEFT JOIN wallet.wallets w ON w.wallet_id = t.wallet_id
     WHERE w.wallet_id IS NULL$q$),

('TXN_WITHDRAWAL_FEE', 'Withdrawal fee does not follow the fee rule', 'consistency', 'wallet.transactions', 'high', 'Finance',
 'Instant withdrawal fee = 1.5% of the amount, at least 0.25 and at most 15.00, rounded to the cent (FSD-2026-031 BR-03).',
 $q$SELECT txn_id::text, 'amount ' || amount || ', fee charged ' || fee || ', expected ' ||
           round(least(greatest(amount * 0.015, 0.25), 15.00), 2)
      FROM wallet.transactions
     WHERE txn_type = 'withdrawal' AND amount > 0
       AND fee IS DISTINCT FROM round(least(greatest(amount * 0.015, 0.25), 15.00), 2)$q$),

('LEDGER_ARITHMETIC', 'Ledger closing balance does not add up', 'consistency', 'wallet.daily_ledger', 'critical', 'Finance',
 'For every wallet and day: closing = opening + credits - debits.',
 $q$SELECT wallet_id || '@' || ledger_date, 'opening ' || opening_balance || ' + credits ' || total_credits ||
           ' - debits ' || total_debits || ' = ' || (opening_balance + total_credits - total_debits) ||
           ', but closing is ' || closing_balance
      FROM wallet.daily_ledger WHERE closing_balance <> opening_balance + total_credits - total_debits$q$),

('LEDGER_TXN_RECON', 'Ledger does not match the transactions', 'consistency', 'wallet.daily_ledger', 'critical', 'Finance',
 'Daily ledger credits and debits must equal the completed transactions for that wallet and day.',
 $q$WITH t AS (
      SELECT wallet_id, created_at::date AS d,
             sum(CASE WHEN txn_type IN ('deposit', 'p2p_receive') THEN amount ELSE 0 END) AS credits,
             sum(CASE WHEN txn_type IN ('withdrawal', 'p2p_send') THEN amount + coalesce(fee, 0) ELSE 0 END) AS debits
        FROM wallet.transactions WHERE status = 'completed' GROUP BY 1, 2)
    SELECT coalesce(l.wallet_id, t.wallet_id) || '@' || coalesce(l.ledger_date, t.d),
           'ledger credits/debits ' || coalesce(l.total_credits, 0) || '/' || coalesce(l.total_debits, 0) ||
           ', transactions ' || coalesce(t.credits, 0) || '/' || coalesce(t.debits, 0)
      FROM wallet.daily_ledger l FULL JOIN t ON t.wallet_id = l.wallet_id AND t.d = l.ledger_date
     WHERE coalesce(l.total_credits, 0) <> coalesce(t.credits, 0) OR coalesce(l.total_debits, 0) <> coalesce(t.debits, 0)$q$),

('FEED_FRESHNESS', 'Source feed is late', 'timeliness', 'wallet.feed_loads', 'high', 'Data engineering',
 'Each source feed must have loaded within its service level (sla_hours).',
 $q$SELECT feed_name, source_system || ' last loaded ' || round(extract(epoch FROM now() - last_loaded_at) / 3600, 1) ||
           ' h ago; SLA ' || sla_hours || ' h'
      FROM wallet.feed_loads WHERE last_loaded_at IS NULL OR last_loaded_at < now() - make_interval(hours => sla_hours)$q$),

('TXN_VOLUME_DROP', 'Daily transaction volume dropped sharply', 'volume', 'wallet.transactions', 'high', 'Data engineering',
 'Yesterday (the latest complete UTC day) should have at least half the average daily volume of the 7 days before it. A day with no transactions at all counts as 0.',
 $q$WITH latest AS (SELECT current_date - 1 AS d),
    daily AS (
      SELECT created_at::date AS d, count(*) AS n FROM wallet.transactions
       WHERE created_at >= current_date - 8 AND created_at < current_date GROUP BY 1),
    base AS (SELECT avg(coalesce(daily.n, 0)) AS avg_n
               FROM latest, generate_series(latest.d - 7, latest.d - 1, interval '1 day') g(day)
               LEFT JOIN daily ON daily.d = g.day::date)
    SELECT latest.d::text, coalesce(daily.n, 0) || ' transactions vs a 7-day average of ' || round(base.avg_n)
      FROM latest CROSS JOIN base LEFT JOIN daily ON daily.d = latest.d
     WHERE coalesce(daily.n, 0) < 0.5 * base.avg_n$q$)

ON CONFLICT (rule_code) DO UPDATE SET
  rule_name = EXCLUDED.rule_name, dimension = EXCLUDED.dimension, table_name = EXCLUDED.table_name,
  severity = EXCLUDED.severity, owner = EXCLUDED.owner, description = EXCLUDED.description, check_sql = EXCLUDED.check_sql;
