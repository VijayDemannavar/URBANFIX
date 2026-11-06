export const categories = [
  "Road Damage",
  "Waterlogging",
  "Garbage Overflow",
  "Streetlight",
  "Drainage",
  "Public Safety",
  "Water Supply",
  "Sewage",
  "Tree / Vegetation",
  "Noise Pollution",
  "Other",
];
export const statuses = [
  "Submitted",
  "Under Review",
  "Assigned",
  "In Progress",
  "Resolved",
  "Closed",
  "Rejected",
];
export const priorityLevels = ["Low", "Medium", "High", "Critical"];
export const departmentNames = [
  "Public Works",
  "Water & Sanitation",
  "Waste Management",
  "Electrical Department",
  "Traffic & Safety",
  "Parks & Environment",
];
export const categoryDepartment: Record<string, string> = {
  "Road Damage": departmentNames[0],
  Waterlogging: departmentNames[1],
  Drainage: departmentNames[1],
  Sewage: departmentNames[1],
  "Water Supply": departmentNames[1],
  "Garbage Overflow": departmentNames[2],
  Streetlight: departmentNames[3],
  "Public Safety": departmentNames[4],
  "Noise Pollution": departmentNames[5],
  "Tree / Vegetation": departmentNames[5],
  Other: departmentNames[0],
};
