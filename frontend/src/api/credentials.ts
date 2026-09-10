import { request } from './http';
import type { Credential } from '../types';

export interface CredentialPayload {
  name: string;
  proxy?: string;
  cookies?: string;
  custom_headers?: Record<string, string>;
}

export const credentialApi = {
  list: () => request.get<Credential[]>('/credentials'),
  create: (data: CredentialPayload) =>
    request.post<{ id: string }>('/credentials', data),
  update: (id: string, data: Partial<CredentialPayload>) =>
    request.put<void>(`/credentials/${id}`, data),
  remove: (id: string) => request.del<void>(`/credentials/${id}`),
};
