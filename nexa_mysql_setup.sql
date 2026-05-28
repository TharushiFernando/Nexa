CREATE DATABASE IF NOT EXISTS nexa_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE nexa_ai;

CREATE TABLE IF NOT EXISTS nexa_chat_logs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    log_id VARCHAR(64) NOT NULL,
    user_name TEXT NOT NULL,
    user_prompt LONGTEXT NOT NULL,
    nexa_response LONGTEXT NOT NULL,
    timestamp_utc DATETIME NOT NULL,
    stars TINYINT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_log_id (log_id),
    KEY idx_timestamp_utc (timestamp_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO nexa_chat_logs (
    log_id,
    user_name,
    user_prompt,
    nexa_response,
    timestamp_utc,
    stars
) VALUES
('seed-001', 'Asha', 'What is photosynthesis?', 'Photosynthesis is the process where green plants use sunlight, water, and carbon dioxide to make food and release oxygen.', '2026-05-27 09:00:00', 5),
('seed-002', 'Asha', 'Explain the water cycle in simple words.', 'The water cycle is the continuous movement of water from oceans and rivers into the air, then back to the ground as rain.', '2026-05-27 09:08:00', 4),
('seed-003', 'Malik', 'Give me three examples of renewable energy.', 'Three examples of renewable energy are solar energy, wind energy, and hydropower.', '2026-05-27 09:15:00', 5),
('seed-004', 'Malik', 'What is an ecosystem?', 'An ecosystem is a place where living things and non-living things interact together.', '2026-05-27 09:22:00', 4),
('seed-005', 'Sana', 'Write a short note on the digestive system.', 'The digestive system breaks down food into smaller parts so the body can absorb nutrients and use them for energy.', '2026-05-27 09:31:00', 5),
('seed-006', 'Sana', 'What are the stages of the water cycle?', 'The main stages are evaporation, condensation, precipitation, and collection.', '2026-05-27 09:40:00', 3),
('seed-007', 'Asha', 'Why do plants need sunlight?', 'Plants need sunlight to make food through photosynthesis.', '2026-05-27 09:48:00', 5),
('seed-008', 'Malik', 'Can you define climate?', 'Climate is the usual weather pattern of a place over a long period of time.', '2026-05-27 09:55:00', 4);
