-- Creates the database for the regulatory change tracker. Runs once, when the Postgres container is first created.
CREATE DATABASE reg_tracker;
-- Dates and "days until deadline" are calculated in UTC for every client.
ALTER DATABASE reg_tracker SET timezone TO 'UTC';
