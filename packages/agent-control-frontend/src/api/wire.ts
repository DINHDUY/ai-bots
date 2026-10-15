import Ajv2020 from "ajv/dist/2020";
import schema from "./events.schema.json";
import type { WireFrame } from "./events.generated";

const validate = new Ajv2020({ strict: false, allErrors: false }).compile<WireFrame>(schema);

export function parseWireFrame(raw: string): WireFrame {
  const frame: unknown = JSON.parse(raw);
  if (!validate(frame)) throw new Error("Unsupported or malformed server event.");
  return frame;
}
