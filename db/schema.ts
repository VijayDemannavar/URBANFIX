import {
  pgTable,
  serial,
  text,
  integer,
  doublePrecision,
  timestamp,
  index,
  primaryKey,
} from "drizzle-orm/pg-core";
const created = () =>
  timestamp("created_at", { mode: "string" }).notNull().defaultNow();
export const departments = pgTable("departments", {
  id: serial().primaryKey(),
  department_name: text().notNull().unique(),
  description: text(),
});
export const officers = pgTable("officers", {
  id: serial().primaryKey(),
  officer_name: text().notNull(),
  department_id: integer()
    .notNull()
    .references(() => departments.id),
  created_at: created(),
});
export const complaints = pgTable(
  "complaints",
  {
    id: serial().primaryKey(),
    complaint_id: text().notNull().unique(),
    title: text().notNull(),
    description: text().notNull(),
    category: text().notNull(),
    ai_category: text(),
    ai_summary: text(),
    ai_confidence: doublePrecision(),
    ai_explanation: text(),
    ai_needs_review: integer().notNull().default(0),
    ai_suggested_dept: text(),
    ai_feedback: text(),
    image_path: text(),
    latitude: doublePrecision(),
    longitude: doublePrecision(),
    address: text(),
    priority_score: doublePrecision().notNull().default(0),
    priority_level: text().notNull().default("Low"),
    priority_reason: text(),
    status: text().notNull().default("Submitted"),
    department_id: integer().references(() => departments.id),
    assigned_officer: integer().references(() => officers.id),
    created_at: created(),
    updated_at: timestamp({ mode: "string" }).notNull().defaultNow(),
    resolved_at: timestamp({ mode: "string" }),
    resolution_message: text(),
    resolution_image_path: text(),
  },
  (t) => [
    index("complaints_status_idx").on(t.status),
    index("complaints_created_idx").on(t.created_at),
    index("complaints_location_idx").on(t.latitude, t.longitude),
  ],
);
export const statusHistory = pgTable("status_history", {
  id: serial().primaryKey(),
  complaint_id: text()
    .notNull()
    .references(() => complaints.complaint_id, { onDelete: "cascade" }),
  old_status: text(),
  new_status: text().notNull(),
  action_note: text(),
  changed_at: timestamp({ mode: "string" }).notNull().defaultNow(),
});
export const actionNotes = pgTable("action_notes", {
  id: serial().primaryKey(),
  complaint_id: text()
    .notNull()
    .references(() => complaints.complaint_id, { onDelete: "cascade" }),
  note: text().notNull(),
  created_at: created(),
});
export const duplicateLinks = pgTable("duplicate_links", {
  id: serial().primaryKey(),
  complaint_id: text()
    .notNull()
    .references(() => complaints.complaint_id, { onDelete: "cascade" }),
  matched_complaint_id: text()
    .notNull()
    .references(() => complaints.complaint_id, { onDelete: "cascade" }),
  similarity_score: doublePrecision().notNull(),
  created_at: created(),
});
export const notifications = pgTable("notifications", {
  id: serial().primaryKey(),
  complaint_id: text()
    .notNull()
    .references(() => complaints.complaint_id, { onDelete: "cascade" }),
  title: text().notNull(),
  message: text().notNull(),
  is_read: integer().notNull().default(0),
  created_at: created(),
});
// Opaque cookies reference server-side sessions; no signing secret is needed.
export const sessions = pgTable("sessions", {
  id: text().primaryKey(),
  csrf_token: text().notNull(),
  expires_at: timestamp({ mode: "string" }).notNull(),
});
export const trackedComplaints = pgTable(
  "tracked_complaints",
  {
    session_id: text()
      .notNull()
      .references(() => sessions.id, { onDelete: "cascade" }),
    complaint_id: text()
      .notNull()
      .references(() => complaints.complaint_id, { onDelete: "cascade" }),
  },
  (t) => [primaryKey({ columns: [t.session_id, t.complaint_id] })],
);
