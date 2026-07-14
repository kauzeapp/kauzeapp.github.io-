import AsyncStorage from '@react-native-async-storage/async-storage';

import { initialDemoState } from '../data/demoData';
import { DemoState } from '../types';

const STORAGE_KEY = 'kauzeMobileDemoStateV1';

export async function loadDemoState(): Promise<DemoState> {
  const stored = await AsyncStorage.getItem(STORAGE_KEY);
  if (!stored) return initialDemoState;

  try {
    const parsed = JSON.parse(stored) as Partial<DemoState>;
    return {
      ...initialDemoState,
      ...parsed,
      appointments: Array.isArray(parsed.appointments)
        ? parsed.appointments
        : initialDemoState.appointments,
    };
  } catch {
    return initialDemoState;
  }
}

export async function saveDemoState(state: DemoState): Promise<void> {
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export async function resetDemoState(): Promise<DemoState> {
  await AsyncStorage.removeItem(STORAGE_KEY);
  return initialDemoState;
}
