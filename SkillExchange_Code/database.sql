-- USERS TABLE
CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password TEXT NOT NULL,
    bio TEXT,
    profile_pic TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- SKILLS TABLE
CREATE TABLE IF NOT EXISTS skills (
    skill_id SERIAL PRIMARY KEY,
    skill_name VARCHAR(100) UNIQUE NOT NULL
);

-- USER SKILLS
CREATE TABLE IF NOT EXISTS user_skills (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(user_id) ON DELETE CASCADE,
    skill_id INT REFERENCES skills(skill_id) ON DELETE CASCADE,
    type VARCHAR(10) CHECK (type IN ('offer', 'want'))
);

-- CONNECTIONS
CREATE TABLE IF NOT EXISTS connections (
    connection_id SERIAL PRIMARY KEY,
    sender_id INT REFERENCES users(user_id),
    receiver_id INT REFERENCES users(user_id),
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- VIDEOS
CREATE TABLE IF NOT EXISTS videos (
    video_id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(user_id) ON DELETE CASCADE,
    title VARCHAR(200),
    description TEXT,
    video_url TEXT,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- RATINGS
CREATE TABLE IF NOT EXISTS ratings (
    rating_id SERIAL PRIMARY KEY,
    video_id INT REFERENCES videos(video_id) ON DELETE CASCADE,
    user_id INT REFERENCES users(user_id),
    rating INT CHECK (rating >= 1 AND rating <= 5),
    review TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ANALYTICS
CREATE TABLE IF NOT EXISTS analytics (
    analytics_id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(user_id),
    date DATE DEFAULT CURRENT_DATE,
    videos_uploaded INT DEFAULT 0,
    connections_made INT DEFAULT 0,
    profile_views INT DEFAULT 0
);

-- SUPPLEMENTAL TABLES
CREATE TABLE IF NOT EXISTS likes (
    like_id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(user_id),
    video_id INT REFERENCES videos(video_id),
    UNIQUE(user_id, video_id)
);

CREATE TABLE IF NOT EXISTS comments (
    comment_id SERIAL PRIMARY KEY,
    video_id INT REFERENCES videos(video_id),
    user_id INT REFERENCES users(user_id),
    comment_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    message_id SERIAL PRIMARY KEY,
    sender_id INT REFERENCES users(user_id),
    receiver_id INT REFERENCES users(user_id),
    message_text TEXT NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    attachment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(user_id),
    source_user_id INT REFERENCES users(user_id),
    type VARCHAR(40) NOT NULL,
    message TEXT NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
