DROP TABLE IF EXISTS events;

CREATE TABLE events (
    short_name TEXT NOT NULL,
    name TEXT NOT NULL,
    event_type TEXT,
    categories TEXT[],
    tags TEXT[],
    summary TEXT,
    organizer TEXT,
    cost NUMERIC,
    source_created_at TIMESTAMP WITH TIME ZONE,
    source_json_name TEXT,
    source_whatsapp_group TEXT,
    venue_name TEXT,
    venue_address_llm TEXT,
    contact_string TEXT,
    area VARCHAR(255),
    post_datetime TIMESTAMP WITH TIME ZONE,
    start_date DATE,
    start_time TIME WITH TIME ZONE,
    end_date DATE,
    end_time TIME WITH TIME ZONE,
    is_update BOOLEAN,
    is_cancelled BOOLEAN,
    info_link TEXT,
    reg_link TEXT,
    gmaps_link TEXT,
    notes_to_admin TEXT,
    -- dynamically created
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    -- processed columns
    source VARCHAR(255),
    event_id TEXT PRIMARY KEY,
    lat_long GEOGRAPHY(Point, 4326),
    venue_address_gmaps TEXT
);