export type RiskLevel = "low" | "medium" | "high";

export interface ActionProvenance {
  source_intent: string;
  orchestrator_task_id?: string;
  model_version?: string;
  generated_at?: string; // ISO string
}

export interface ActionTarget {
  device_id: string;
  device_class: string;
  location?: string;
  endpoint?: string;
}

export interface ActionIntent {
  name: string;
  parameters: Record<string, unknown>;
  human_readable?: string;
}

export interface ActionConstraints {
  max_duration_ms?: number;
  required_confirmations?: number;
  quiet_hours?: string[];
  allowed_risk_levels?: RiskLevel[];
}

export interface PolicyContext {
  scopes?: string[];
  consent_reference?: string;
  justification?: string;
  risk_level?: RiskLevel;
}

export interface TelemetryChannel {
  topic: string;
  delivery?: "stream" | "batch";
  include_parameters?: boolean;
}

export interface ActionEnvelope {
  schema_version: "1.0";
  action_id: string;
  person_id: string;
  target: ActionTarget;
  intent: ActionIntent;
  risk_level: RiskLevel;
  constraints?: ActionConstraints;
  policy_context?: PolicyContext;
  telemetry_channel?: TelemetryChannel;
  provenance?: ActionProvenance;
  created_at?: string;
  correlation_id?: string;
}
