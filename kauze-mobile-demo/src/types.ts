export type AppRole = 'client' | 'business' | 'professional' | 'admin';

export type Category =
  | 'barberia'
  | 'manicure'
  | 'pestanas'
  | 'estetica'
  | 'peluqueria';

export type BusinessStatus = 'Disponible' | 'Ocupado' | 'Pausado';

export type AppointmentStatus =
  | 'Esperando confirmación'
  | 'Confirmada'
  | 'En servicio'
  | 'Completada'
  | 'Cancelada'
  | 'No asistió';

export interface Service {
  id: string;
  name: string;
  durationMinutes: number;
  priceClp: number;
}

export interface Professional {
  id: string;
  name: string;
  specialty: string;
}

export interface Business {
  id: string;
  name: string;
  category: Category;
  location: string;
  rating: number;
  services: Service[];
  professionals: Professional[];
}

export interface Appointment {
  id: string;
  businessId: string;
  clientName: string;
  clientPhone: string;
  serviceId: string;
  professionalId: string;
  startsAt: string;
  priceClp: number;
  status: AppointmentStatus;
  paymentStatus: 'Sin abono' | 'Pagado demo';
}

export interface DemoState {
  appointments: Appointment[];
  businessStatus: BusinessStatus;
  depositEnabled: boolean;
  depositPercent: number;
}
