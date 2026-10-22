export const MAX_IMAGE_BYTES = 3 * 1024 * 1024;
export function validImage(file: { size: number; type: string }) {
  return file.size > 0 && file.size <= MAX_IMAGE_BYTES &&
    ["image/png", "image/jpeg", "image/webp"].includes(file.type);
}
export function base64Image(bytes: Uint8Array) {
  if (!bytes.length || bytes.length > MAX_IMAGE_BYTES) throw "VISION.IMAGE_LIMIT";
  let text = "";
  for (let start = 0; start < bytes.length; start += 32768)
    text += String.fromCharCode(...bytes.subarray(start, start + 32768));
  return btoa(text);
}
