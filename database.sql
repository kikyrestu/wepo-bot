-- Buat database jika belum ada
CREATE DATABASE IF NOT EXISTS discord_bot;
USE discord_bot;

-- Tabel untuk developer credentials
CREATE TABLE IF NOT EXISTS dev_credentials (
    user_id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    token VARCHAR(255),
    last_login TIMESTAMP NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk dev sessions
CREATE TABLE IF NOT EXISTS dev_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id BIGINT,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES dev_credentials(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk dev logs
CREATE TABLE IF NOT EXISTS dev_logs (
    log_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT,
    action VARCHAR(255),
    details TEXT,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES dev_credentials(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk welcome messages
CREATE TABLE IF NOT EXISTS welcome_messages (
    guild_id BIGINT PRIMARY KEY,
    message TEXT,
    channel_id BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk music queue
CREATE TABLE IF NOT EXISTS music_queue (
    id INT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT,
    url TEXT,
    title VARCHAR(255),
    duration VARCHAR(10),
    position INT,
    INDEX idx_guild (guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk roles
CREATE TABLE IF NOT EXISTS server_roles (
    guild_id BIGINT,
    role_type VARCHAR(50),
    role_id BIGINT,
    PRIMARY KEY (guild_id, role_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk temporary roles
CREATE TABLE IF NOT EXISTS temp_roles (
    user_id BIGINT,
    role_id BIGINT,
    guild_id BIGINT,
    expiry TIMESTAMP,
    PRIMARY KEY (user_id, role_id),
    INDEX idx_expiry (expiry),
    INDEX idx_guild (guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk filter words
CREATE TABLE IF NOT EXISTS filter_words (
    guild_id BIGINT,
    word VARCHAR(255),
    PRIMARY KEY (guild_id, word),
    INDEX idx_guild (guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk filter settings
CREATE TABLE IF NOT EXISTS filter_settings (
    guild_id BIGINT PRIMARY KEY,
    max_words INT DEFAULT 5,  -- Max words for free tier
    links_enabled BOOLEAN DEFAULT FALSE,
    invites_enabled BOOLEAN DEFAULT FALSE,
    auto_warn BOOLEAN DEFAULT FALSE,
    auto_mute BOOLEAN DEFAULT FALSE,
    mute_duration INT DEFAULT 300,  -- 5 menit dalam detik
    warn_threshold INT DEFAULT 3     -- Auto mute setelah 3 warn
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk filter channels
CREATE TABLE IF NOT EXISTS filter_channels (
    guild_id BIGINT,
    channel_id BIGINT,
    PRIMARY KEY (guild_id, channel_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk filter bypass roles
CREATE TABLE IF NOT EXISTS filter_bypass (
    guild_id BIGINT,
    role_id BIGINT,
    PRIMARY KEY (guild_id, role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk tickets
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT,
    channel_id BIGINT,
    user_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP NULL,
    status ENUM('open', 'closed') DEFAULT 'open',
    INDEX idx_guild (guild_id),
    INDEX idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk ticket settings
CREATE TABLE IF NOT EXISTS ticket_settings (
    guild_id BIGINT PRIMARY KEY,
    category_id BIGINT,
    staff_role_id BIGINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk bot settings
CREATE TABLE IF NOT EXISTS bot_settings (
    setting_id INT AUTO_INCREMENT PRIMARY KEY,
    setting_name VARCHAR(255) UNIQUE,
    setting_value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk broadcast messages
CREATE TABLE IF NOT EXISTS broadcast_messages (
    broadcast_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT,
    message TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status ENUM('pending', 'sending', 'completed', 'failed') DEFAULT 'pending',
    total_servers INT DEFAULT 0,
    successful_sends INT DEFAULT 0,
    failed_sends INT DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES dev_credentials(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk custom responses
CREATE TABLE IF NOT EXISTS custom_responses (
    response_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT,
    trigger_word VARCHAR(100),
    response TEXT,
    created_by BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE KEY unique_trigger (guild_id, trigger_word)
);

-- Tabel untuk trial/premium
CREATE TABLE IF NOT EXISTS premium_trials (
    guild_id BIGINT PRIMARY KEY,
    activated_by BIGINT,
    start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_date TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    INDEX idx_end_date (end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk advanced welcome system
CREATE TABLE IF NOT EXISTS welcome_settings (
    guild_id BIGINT PRIMARY KEY,
    is_embed BOOLEAN DEFAULT FALSE,
    embed_title VARCHAR(255),
    embed_description TEXT,
    embed_color VARCHAR(7),
    embed_thumbnail TEXT,
    embed_image TEXT,
    footer_text TEXT,
    INDEX idx_guild (guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk auto roles
CREATE TABLE IF NOT EXISTS welcome_autoroles (
    guild_id BIGINT,
    role_id BIGINT,
    PRIMARY KEY (guild_id, role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk member warnings
CREATE TABLE IF NOT EXISTS member_warnings (
    warning_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT,
    user_id BIGINT,
    reason TEXT,
    warned_by BIGINT,
    warned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_member (guild_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel untuk reminder settings
CREATE TABLE IF NOT EXISTS reminder_settings (
    guild_id BIGINT PRIMARY KEY,
    notify_channel_id BIGINT,
    notify_days INT DEFAULT 1,  -- Notif H-berapa sebelum expired
    last_reminder TIMESTAMP,
    INDEX idx_guild (guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Insert default developer (ganti USER_ID dan HASHED_TOKEN dengan nilai yang sesuai)
-- INSERT INTO dev_credentials (user_id, username, token) 
-- VALUES (USER_ID, 'Developer', 'HASHED_TOKEN');

-- Insert default bot settings
INSERT INTO bot_settings (setting_name, setting_value) VALUES
('prefix', '!'),
('status_type', 'playing'),
('status_text', 'Type !help'),
('color_theme', '#7289DA'),
('log_channel', '0'),
('maintenance_mode', 'false'); 