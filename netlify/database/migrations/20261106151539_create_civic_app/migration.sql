CREATE TABLE "action_notes" (
	"id" serial PRIMARY KEY,
	"complaint_id" text NOT NULL,
	"note" text NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "complaints" (
	"id" serial PRIMARY KEY,
	"complaint_id" text NOT NULL UNIQUE,
	"title" text NOT NULL,
	"description" text NOT NULL,
	"category" text NOT NULL,
	"ai_category" text,
	"ai_summary" text,
	"ai_confidence" double precision,
	"ai_explanation" text,
	"ai_needs_review" integer DEFAULT 0 NOT NULL,
	"ai_suggested_dept" text,
	"ai_feedback" text,
	"image_path" text,
	"latitude" double precision,
	"longitude" double precision,
	"address" text,
	"priority_score" double precision DEFAULT 0 NOT NULL,
	"priority_level" text DEFAULT 'Low' NOT NULL,
	"priority_reason" text,
	"status" text DEFAULT 'Submitted' NOT NULL,
	"department_id" integer,
	"assigned_officer" integer,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	"resolved_at" timestamp,
	"resolution_message" text,
	"resolution_image_path" text
);
--> statement-breakpoint
CREATE TABLE "departments" (
	"id" serial PRIMARY KEY,
	"department_name" text NOT NULL UNIQUE,
	"description" text
);
--> statement-breakpoint
CREATE TABLE "duplicate_links" (
	"id" serial PRIMARY KEY,
	"complaint_id" text NOT NULL,
	"matched_complaint_id" text NOT NULL,
	"similarity_score" double precision NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "notifications" (
	"id" serial PRIMARY KEY,
	"complaint_id" text NOT NULL,
	"title" text NOT NULL,
	"message" text NOT NULL,
	"is_read" integer DEFAULT 0 NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "officers" (
	"id" serial PRIMARY KEY,
	"officer_name" text NOT NULL,
	"department_id" integer NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "sessions" (
	"id" text PRIMARY KEY,
	"csrf_token" text NOT NULL,
	"expires_at" timestamp NOT NULL
);
--> statement-breakpoint
CREATE TABLE "status_history" (
	"id" serial PRIMARY KEY,
	"complaint_id" text NOT NULL,
	"old_status" text,
	"new_status" text NOT NULL,
	"action_note" text,
	"changed_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "tracked_complaints" (
	"session_id" text,
	"complaint_id" text,
	CONSTRAINT "tracked_complaints_pkey" PRIMARY KEY("session_id","complaint_id")
);
--> statement-breakpoint
CREATE INDEX "complaints_status_idx" ON "complaints" ("status");--> statement-breakpoint
CREATE INDEX "complaints_created_idx" ON "complaints" ("created_at");--> statement-breakpoint
CREATE INDEX "complaints_location_idx" ON "complaints" ("latitude","longitude");--> statement-breakpoint
ALTER TABLE "action_notes" ADD CONSTRAINT "action_notes_complaint_id_complaints_complaint_id_fkey" FOREIGN KEY ("complaint_id") REFERENCES "complaints"("complaint_id") ON DELETE CASCADE;--> statement-breakpoint
ALTER TABLE "complaints" ADD CONSTRAINT "complaints_department_id_departments_id_fkey" FOREIGN KEY ("department_id") REFERENCES "departments"("id");--> statement-breakpoint
ALTER TABLE "complaints" ADD CONSTRAINT "complaints_assigned_officer_officers_id_fkey" FOREIGN KEY ("assigned_officer") REFERENCES "officers"("id");--> statement-breakpoint
ALTER TABLE "duplicate_links" ADD CONSTRAINT "duplicate_links_complaint_id_complaints_complaint_id_fkey" FOREIGN KEY ("complaint_id") REFERENCES "complaints"("complaint_id") ON DELETE CASCADE;--> statement-breakpoint
ALTER TABLE "duplicate_links" ADD CONSTRAINT "duplicate_links_5wPBSPZdE1uv_fkey" FOREIGN KEY ("matched_complaint_id") REFERENCES "complaints"("complaint_id") ON DELETE CASCADE;--> statement-breakpoint
ALTER TABLE "notifications" ADD CONSTRAINT "notifications_complaint_id_complaints_complaint_id_fkey" FOREIGN KEY ("complaint_id") REFERENCES "complaints"("complaint_id") ON DELETE CASCADE;--> statement-breakpoint
ALTER TABLE "officers" ADD CONSTRAINT "officers_department_id_departments_id_fkey" FOREIGN KEY ("department_id") REFERENCES "departments"("id");--> statement-breakpoint
ALTER TABLE "status_history" ADD CONSTRAINT "status_history_complaint_id_complaints_complaint_id_fkey" FOREIGN KEY ("complaint_id") REFERENCES "complaints"("complaint_id") ON DELETE CASCADE;--> statement-breakpoint
ALTER TABLE "tracked_complaints" ADD CONSTRAINT "tracked_complaints_session_id_sessions_id_fkey" FOREIGN KEY ("session_id") REFERENCES "sessions"("id") ON DELETE CASCADE;--> statement-breakpoint
ALTER TABLE "tracked_complaints" ADD CONSTRAINT "tracked_complaints_complaint_id_complaints_complaint_id_fkey" FOREIGN KEY ("complaint_id") REFERENCES "complaints"("complaint_id") ON DELETE CASCADE;