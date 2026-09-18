import type {
  ConnectionProfile,
  DeviceEntries,
  DeviceKind,
  DeviceSlot,
  DeviceState,
  DriverInfo,
  PreviewData,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    const detail = payload.detail;
    const message = typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new Error(message || "请求失败");
  }
  return response.json() as Promise<T>;
}

export const api = {
  drivers: () => request<DriverInfo[]>("/api/v1/devices/drivers"),
  state: () => request<DeviceState>("/api/v1/devices/state"),
  profiles: () => request<ConnectionProfile[]>("/api/v1/connection-profiles"),
  discover: (kind: DeviceKind, driver_id: string, config: Record<string, unknown>) =>
    request<DeviceSlot>(`/api/v1/devices/${kind}/discover`, {
      method: "POST",
      body: JSON.stringify({ driver_id, config }),
    }),
  connect: (kind: DeviceKind, driver_id: string, config: Record<string, unknown>) =>
    request<DeviceSlot>(`/api/v1/devices/${kind}/connect`, {
      method: "POST",
      body: JSON.stringify({ driver_id, config }),
    }),
  disconnect: (kind: DeviceKind) =>
    request<DeviceSlot>(`/api/v1/devices/${kind}/disconnect`, { method: "POST" }),
  preview: (kind: DeviceKind) => request<PreviewData>(`/api/v1/devices/${kind}/preview`),
  saveProfile: (id: string | null, name: string, devices: DeviceEntries) =>
    request<ConnectionProfile>("/api/v1/connection-profiles", {
      method: "POST",
      body: JSON.stringify({ id, name, devices }),
    }),
};
