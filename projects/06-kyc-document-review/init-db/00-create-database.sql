-- Creates the KYC database. Runs once, when the Postgres container is first created.
CREATE DATABASE kyc;
ALTER DATABASE kyc SET timezone TO 'UTC';
