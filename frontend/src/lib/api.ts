import axios, { type AxiosInstance } from "axios";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api";

/**
 * Shared axios instance — single base URL, no auth wiring yet. PR2's
 * optional bearer-token flow uses ``Authorization: Bearer`` headers;
 * clients that enable ``API_ACCESS_TOKEN`` can configure an interceptor
 * here when that setting lands in the settings panel.
 */
export const api: AxiosInstance = axios.create({ baseURL: API_BASE });
