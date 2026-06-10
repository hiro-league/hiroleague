import { apiRequest, type ApiResponse } from './client';

export type ImageLabModelRow = {
  id: string;
  display_name: string;
  provider_id: string;
  provider_display_name: string;
  /** Provider configured AND (for cloudflare-style vendors) account id present. */
  available: boolean;
  configured: boolean;
  notes: string | null;
  per_image: number | null;
  per_step: number | null;
};

export type ImageProfile = {
  label: string;
  locked: boolean;
  model: string | null;
  steps: number;
  size: string | null;
  style_prefix: string;
  style_suffix: string;
  seed: number | null;
};

export type ImageLabOptions = {
  models: ImageLabModelRow[];
  profiles: Record<string, ImageProfile>;
  default_profile: string;
  default_model: string | null;
};

export type ImageLabGenerateRequest = {
  prompt: string;
  profile_id?: string | null;
  model?: string | null;
  steps?: number | null;
  seed?: number | null;
};

export type ImageLabGenerateResult = {
  image_base64: string;
  mime_type: string;
  model: string;
  provider: string;
  profile: string;
  steps: number;
  seed: number | null;
  width: number | null;
  height: number | null;
  prompt_used: string;
  elapsed_ms: number;
  estimated_cost_usd: number | null;
};

export async function getImageLabOptions(): Promise<ApiResponse<ImageLabOptions>> {
  return apiRequest<ImageLabOptions>('/image-lab/options');
}

export async function generateImage(
  body: ImageLabGenerateRequest
): Promise<ApiResponse<ImageLabGenerateResult>> {
  // Diffusion + retries can take a while; well past the default 20s API timeout.
  return apiRequest<ImageLabGenerateResult>('/image-lab/generate', {
    method: 'POST',
    body,
    timeoutMs: 120000
  });
}
