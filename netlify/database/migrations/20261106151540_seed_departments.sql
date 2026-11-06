INSERT INTO departments (department_name, description) VALUES
('Public Works', 'Manages roads, bridges, and public infrastructure'),
('Water & Sanitation', 'Handles water supply, sewage, and drainage systems'),
('Waste Management', 'Responsible for garbage collection and disposal'),
('Electrical Department', 'Manages streetlights and public electrical infrastructure'),
('Traffic & Safety', 'Manages public safety, traffic signals, and hazards'),
('Parks & Environment', 'Oversees parks, trees, and environmental complaints')
ON CONFLICT (department_name) DO NOTHING;
