import { Appointment, Business, DemoState } from '../types';

export const API_CONFIG = {
  demoMode: true,
  baseUrl: '',
} as const;

export interface KauzeApi {
  listBusinesses(): Promise<Business[]>;
  listAppointments(): Promise<Appointment[]>;
  createAppointment(input: Appointment): Promise<Appointment>;
  updateAppointmentStatus(id: string, status: Appointment['status']): Promise<void>;
  getBusinessState(): Promise<DemoState>;
}

/**
 * Punto de conexión futuro para web, paneles y app móvil.
 * La aplicación nunca debe conectarse directamente a PostgreSQL.
 * Aquí se implementarán llamadas HTTPS al backend FastAPI/REST.
 */
export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  if (API_CONFIG.demoMode || !API_CONFIG.baseUrl) {
    throw new Error('La API real aún no está habilitada; la app funciona en modo demo local.');
  }

  const response = await fetch(`${API_CONFIG.baseUrl}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`Error de API: ${response.status}`);
  }

  return (await response.json()) as T;
}
