export type DeviceKind = "eeg" | "emg" | "glove";

export type FieldSchema = {
  type: "string" | "number" | "integer" | "boolean";
  title?: string;
  default?: string | number | boolean;
  minimum?: number;
  maximum?: number;
  enum?: Array<string | number>;
};

export type ConfigSchema = {
  type: "object";
  properties: Record<string, FieldSchema>;
  required?: string[];
};

export type DriverInfo = {
  id: string;
  kind: DeviceKind;
  display_name: string;
  description: string;
  config_schema: ConfigSchema;
  available: boolean;
  maturity: "simulator" | "prototype" | "experimental" | "reserved";
  unavailable_reason?: string;
};

export type DeviceHealth = {
  transport_ok: boolean;
  stream_ok: boolean;
  time_sync_ok: boolean;
  signal_ok: boolean;
  control_ready: boolean;
  reason: string;
};

export type DeviceSlot = {
  kind: DeviceKind;
  driver_id: string | null;
  state: string;
  config: Record<string, unknown>;
  health: DeviceHealth;
  discovered: Array<{ id: string; name: string; rssi?: number | null }>;
};

export type DeviceState = {
  settings_locked: boolean;
  devices: Record<DeviceKind, DeviceSlot>;
};

export type DeviceEntry = {
  driver_id: string;
  config: Record<string, unknown>;
};

export type DeviceEntries = Record<DeviceKind, DeviceEntry>;

export type ConnectionProfile = {
  id: string;
  name: string;
  devices: DeviceEntries;
  created_at: string;
  updated_at: string;
};

export type PreviewData = {
  kind: DeviceKind;
  samples?: number[][];
  sample_rate?: number;
  channel_names?: string[];
  signal_quality?: number;
  packet_loss?: number;
  position?: number | null;
  target?: number | null;
  armed?: boolean;
  released?: boolean;
  motion_state?: string;
  tension?: number | null;
  notice?: string;
};
