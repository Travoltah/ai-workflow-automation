-- Creates the database the monitor watches and stores its results in.
-- Runs once, when the Postgres container is first created.
CREATE DATABASE contoso_dq;
-- Day boundaries (daily ledger, daily volume) are in UTC for every client, including n8n.
ALTER DATABASE contoso_dq SET timezone TO 'UTC';
