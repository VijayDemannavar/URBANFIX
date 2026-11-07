import { categories } from "./settings.js";
export class HttpError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export const field = (form: FormData, name: string) =>
  typeof form.get(name) === "string" ? String(form.get(name)).trim() : "";
export function validateComplaint(form: FormData) {
  const title = field(form, "title"),
    description = field(form, "description"),
    category = field(form, "category"),
    address = field(form, "address") || null;
  const errors = [];
  if (title.length < 10 || title.length > 160)
    errors.push("Title must be between 10 and 160 characters.");
  if (description.length < 20 || description.length > 2000)
    errors.push("Description must be between 20 and 2000 characters.");
  if (!categories.includes(category)) errors.push("Select a valid category.");
  const coordinate = (key: string, max: number) => {
    const raw = field(form, key);
    if (!raw) return null;
    const value = Number(raw);
    if (!Number.isFinite(value) || Math.abs(value) > max)
      errors.push(
        `${key} must be a valid coordinate between -${max} and ${max}.`,
      );
    return value;
  };
  const latitude = coordinate("latitude", 90),
    longitude = coordinate("longitude", 180);
  if ((latitude === null) !== (longitude === null))
    errors.push("Provide both latitude and longitude.");
  if (address && address.length > 500)
    errors.push("Address must be 500 characters or fewer.");
  return {
    input: { title, description, category, address, latitude, longitude },
    errors,
  };
}
export async function validateImage(value: FormDataEntryValue | null) {
  if (!value || typeof value === "string" || !value.size) return null;
  if (value.size > 4 * 1024 * 1024)
    throw new HttpError(422, "Image must be 4 MB or smaller.");
  const bytes = new Uint8Array(await value.arrayBuffer());
  const start = Buffer.from(bytes.subarray(0, 12));
  let extension = "";
  if (
    start.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
  )
    extension = "png";
  else if (bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255)
    extension = "jpg";
  else if (/^GIF8[79]a/.test(start.toString("ascii"))) extension = "gif";
  else if (
    start.subarray(0, 4).toString() === "RIFF" &&
    start.subarray(8, 12).toString() === "WEBP"
  )
    extension = "webp";
  if (!extension)
    throw new HttpError(422, "Upload a PNG, JPEG, GIF or WebP image.");
  return { bytes: bytes.buffer, extension };
}
export function csvCell(value: unknown) {
  let s = String(value ?? "");
  if (/^[\s]*[=+@-]|^[\t\r]/.test(s)) s = "'" + s;
  return '"' + s.replaceAll('"', '""') + '"';
}
