-- Policy settings for the checks. Change them here, not in code.
\connect kyc

INSERT INTO kyc.settings (key, value) VALUES
('min_age', '18'),
('proof_of_address_max_age_days', '90'),
('max_password_attempts', '3'),
-- ID number formats per issuing country and document type (country codes as on the document).
-- UTO is "Utopia", the fictional specimen state used in ICAO Doc 9303; these formats are invented for the demo.
('id_formats', '{"UTO:passport": "^[A-Z0-9]{9}$", "UTO:national_id": "^\\d{2}-\\d{6}[A-Z]\\d{2}$"}'),
-- Tools that real issuers don't use to produce statements and bills: a PDF made or saved with them is flagged for the reviewer.
('suspicious_producers', '["photoshop", "gimp", "pdf editor", "pdfescape", "sejda", "smallpdf", "ilovepdf", "canva"]')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
