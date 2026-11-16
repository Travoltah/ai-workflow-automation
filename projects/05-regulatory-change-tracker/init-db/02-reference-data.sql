-- Reference data: jurisdictions, the control library, the company profile, and the sources to watch.
-- Markets are data: add a jurisdiction and its sources here, no workflow change needed.

\connect reg_tracker

INSERT INTO reg.jurisdictions (code, name, legal_note) VALUES
('EU', 'European Union', 'EU regulations (such as the GDPR and the AI Act, Regulation (EU) 2024/1689) apply directly in every member state; directives must first be written into national law. Guidelines from EU bodies are not binding but show how the rules will be applied and enforced.'),
('US', 'United States', 'There is no single federal privacy or AI law. Federal agencies make rules through the Federal Register: a proposed rule, a public comment period, then a final rule. States pass their own privacy and AI laws.'),
('UK', 'United Kingdom', 'The UK GDPR and the Data Protection Act 2018 govern personal data. The regulator publishes guidance and statutory codes of practice, usually after a public consultation.'),
('AU', 'Australia', 'The Privacy Act 1988 and the Australian Privacy Principles govern personal information, with guidance from the privacy regulator. Financial institutions also follow prudential standards.'),
('ZW', 'Zimbabwe', 'The Cyber and Data Protection Act (2021) governs personal data, with POTRAZ acting as the Data Protection Authority. The Reserve Bank of Zimbabwe regulates payment systems.'),
('ZA', 'South Africa', 'The Protection of Personal Information Act (POPIA) governs personal information and is enforced by the Information Regulator.')
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, legal_note = EXCLUDED.legal_note;

INSERT INTO reg.controls (control_id, name, description, domain, owner) VALUES
('AI-INVENTORY',        'AI system inventory',                 'A register of every AI system in use, its purpose, owner, data and risk level.', 'AI governance', 'Head of Data & AI'),
('AI-RISK-ASSESS',      'AI risk and impact assessment',       'A documented risk and impact assessment before an AI system goes live and after major changes.', 'AI governance', 'Head of Data & AI'),
('AI-TRANSPARENCY',     'AI interaction disclosure',           'People are told when they interact with an AI system or receive AI-generated content.', 'AI governance', 'Head of Digital Channels'),
('AI-HUMAN-OVERSIGHT',  'Human oversight of AI decisions',     'Named people can review, override and stop AI decisions that affect customers.', 'AI governance', 'Head of Data & AI'),
('AI-MONITORING',       'AI model monitoring',                 'Accuracy, drift, bias and incidents of AI models are monitored and reported.', 'AI governance', 'Head of Data & AI'),
('MODEL-EXPLAIN',       'Explanations of automated decisions', 'Customers can get the main reasons for an automated decision about them in plain language.', 'AI governance', 'Head of Credit Risk'),
('CREDIT-ADVERSE-ACTION','Adverse action notices',             'Declined or reduced credit applications get a notice with the specific reasons.', 'Credit', 'Head of Credit Risk'),
('ADM-REGISTER',        'Register of automated decisions',     'A record of decisions made with significant automation, the data used and the right to human review.', 'Privacy', 'Data Protection Officer'),
('PRIVACY-NOTICE',      'Privacy notice',                      'The privacy notice states what personal data is used, why, how long, with whom, and how automated decisions are made.', 'Privacy', 'Data Protection Officer'),
('DPIA',                'Data protection impact assessment',   'A DPIA is done before high-risk processing such as biometrics, profiling or large-scale monitoring.', 'Privacy', 'Data Protection Officer'),
('RECORDS-OF-PROCESSING','Records of processing activities',   'An up-to-date record of every processing activity, its legal basis and its retention period.', 'Privacy', 'Data Protection Officer'),
('CONSENT-MGMT',        'Consent management',                  'Consent is captured, recorded and can be withdrawn, where consent is the legal basis.', 'Privacy', 'Data Protection Officer'),
('DSAR',                'Data subject requests',               'Access, correction and deletion requests are answered within the legal time limit.', 'Privacy', 'Data Protection Officer'),
('DATA-RETENTION',      'Data retention and deletion',         'Personal data is kept only as long as needed, then deleted or anonymised.', 'Data governance', 'Head of Data Governance'),
('BREACH-NOTIFY',       'Breach notification procedure',       'Personal data breaches are assessed and reported to regulators and customers within the legal deadlines.', 'Security & incidents', 'CISO'),
('BREACH-LOG',          'Breach register',                     'Every personal data breach is logged with facts, effects and remedial action, reported or not.', 'Security & incidents', 'CISO'),
('BIOMETRIC-DATA',      'Biometric data handling',             'Biometric data (face, fingerprint) is collected with a lawful basis, protected and deleted on schedule.', 'Privacy', 'Data Protection Officer'),
('KYC-IDV',             'Customer identity verification',      'Identity checks at onboarding follow the approved method and keep evidence.', 'Compliance', 'Head of Compliance'),
('CROSS-BORDER',        'Cross-border data transfers',         'Transfers of personal data abroad have an approved mechanism and are recorded.', 'Privacy', 'Data Protection Officer'),
('DPA-REGISTRATION',    'Regulator registration and licensing','The company holds and renews any registration or licence the data protection authority requires.', 'Compliance', 'Head of Compliance')
ON CONFLICT (control_id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description, domain = EXCLUDED.domain, owner = EXCLUDED.owner;

INSERT INTO reg.company_profile (id, name, sector, markets, watch_markets, ai_uses, data_types, description) VALUES
(1, 'Contoso Pay (fictional)', 'Fintech: mobile wallet, payments and small loans',
 ARRAY['ZW', 'ZA', 'UK', 'EU'], ARRAY['US', 'AU'],
 ARRAY['credit scoring', 'customer support chatbot', 'fraud detection', 'biometric identity verification (face match)'],
 ARRAY['personal data', 'financial transactions', 'biometric data', 'identity documents'],
 'A mobile wallet with peer-to-peer payments, withdrawals and small loans, operating in Zimbabwe, South Africa, the UK and the EU, and planning to enter the US and Australia. Uses AI for credit decisions, fraud detection, a support chatbot and face-match identity checks.')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, sector = EXCLUDED.sector, markets = EXCLUDED.markets, watch_markets = EXCLUDED.watch_markets,
  ai_uses = EXCLUDED.ai_uses, data_types = EXCLUDED.data_types, description = EXCLUDED.description;

-- Mock sources: fictional regulators served by mock-regulators/server.py, used for the demo and the evaluation.
INSERT INTO reg.sources (code, jurisdiction, regulator, name, method, url, config, topics, is_mock, active) VALUES
('eu-dco-news',     'EU', 'EU Digital Compliance Office (fictional)', 'News and guidance', 'rss', 'http://mock-regulators:8090/eu/feed.xml',
 '{"fetch_pages": true}', ARRAY['AI', 'data protection'], true, true),
('eu-dco-breach',   'EU', 'EU Digital Compliance Office (fictional)', 'Guidance: personal data breach notification', 'html_page', 'http://mock-regulators:8090/eu/guidance/breach-notification.html',
 '{"ignore_patterns": ["^Last updated:"]}', ARRAY['data protection', 'security'], true, true),
('us-fdc-rules',    'US', 'US Federal Data Commission (fictional)', 'Rules and notices', 'json_api', 'http://mock-regulators:8090/us/api/documents.json',
 '{"list": "results", "url": "html_url", "title": "title", "date": "publication_date", "fetch_pages": true}', ARRAY['AI', 'consumer finance'], true, true),
('uk-dsa-consult',  'UK', 'UK Data Standards Authority (fictional)', 'Consultations', 'html_index', 'http://mock-regulators:8090/uk/consultations/index.html',
 '{"link_selector": "a.doc"}', ARRAY['data protection'], true, true),
('uk-dsa-ai',       'UK', 'UK Data Standards Authority (fictional)', 'Guidance: AI and data protection', 'html_page', 'http://mock-regulators:8090/uk/guidance/ai-and-data-protection.html',
 '{}', ARRAY['AI', 'data protection'], true, true),
('au-paio-news',    'AU', 'Australian Privacy and AI Office (fictional)', 'News', 'rss', 'http://mock-regulators:8090/au/feed.xml',
 '{"fetch_pages": true}', ARRAY['privacy', 'AI'], true, true),
('au-paio-register','AU', 'Australian Privacy and AI Office (fictional)', 'Register of determinations', 'html_page', 'http://mock-regulators:8090/au/register.html',
 '{}', ARRAY['privacy'], true, true),
('zw-dpo-notices',  'ZW', 'Zimbabwe Data Protection Office (fictional)', 'Notices', 'html_index', 'http://mock-regulators:8090/zw/notices/index.html',
 '{"link_selector": "a.doc"}', ARRAY['data protection'], true, true),
('zw-dpo-guide',    'ZW', 'Zimbabwe Data Protection Office (fictional)', 'Guide for data controllers', 'html_page', 'http://mock-regulators:8090/zw/guide.html',
 '{}', ARRAY['data protection'], true, true),
('eu-dco-ai-faq',   'EU', 'EU Digital Compliance Office (fictional)', 'AI FAQ', 'html_page', 'http://mock-regulators:8090/eu/guidance/ai-faq.html',
 '{}', ARRAY['AI'], true, true)
ON CONFLICT (code) DO UPDATE SET jurisdiction = EXCLUDED.jurisdiction, regulator = EXCLUDED.regulator, name = EXCLUDED.name, method = EXCLUDED.method,
  url = EXCLUDED.url, config = EXCLUDED.config, topics = EXCLUDED.topics, is_mock = EXCLUDED.is_mock;

-- Real sources, checked reachable on 2026-11-16. Switched OFF by default: switch on with
--   UPDATE reg.sources SET active = true WHERE code = '...';
-- The first check of any source only records a baseline (no AI cost); later checks report what changed.
INSERT INTO reg.sources (code, jurisdiction, regulator, name, method, url, config, topics, is_mock, active, check_every_hours) VALUES
('us-federal-register-ai', 'US', 'Federal Register (all US federal agencies)', 'Documents mentioning artificial intelligence', 'json_api',
 'https://www.federalregister.gov/api/v1/documents.json?per_page=20&order=newest&conditions%5Bterm%5D=%22artificial+intelligence%22',
 '{"list": "results", "url": "html_url", "title": "title", "date": "publication_date", "text": "abstract", "fetch_pages": false}', ARRAY['AI'], false, false, 24),
('us-nist-news', 'US', 'National Institute of Standards and Technology (NIST)', 'News', 'rss',
 'https://www.nist.gov/news-events/news/rss.xml', '{"fetch_pages": false, "max_items": 20}', ARRAY['AI', 'cybersecurity', 'standards'], false, false, 24),
('eu-digital-strategy', 'EU', 'European Commission (Shaping Europe''s digital future)', 'News and policy', 'rss',
 'https://digital-strategy.ec.europa.eu/en/rss.xml', '{"fetch_pages": false, "max_items": 20}', ARRAY['AI', 'data', 'digital'], false, false, 24),
('eu-eurlex-legislation', 'EU', 'EUR-Lex (Publications Office of the EU)', 'All Parliament and Council legislation', 'rss',
 'https://eur-lex.europa.eu/EN/display-feed.rss?rssId=162', '{"fetch_pages": false, "max_items": 30}', ARRAY['legislation'], false, false, 24)
ON CONFLICT (code) DO UPDATE SET jurisdiction = EXCLUDED.jurisdiction, regulator = EXCLUDED.regulator, name = EXCLUDED.name, method = EXCLUDED.method,
  url = EXCLUDED.url, config = EXCLUDED.config, topics = EXCLUDED.topics, is_mock = EXCLUDED.is_mock;
