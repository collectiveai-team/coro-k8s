{{- define "coro.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "coro.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else if contains (include "coro.name" .) .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "coro.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "coro.selectorLabels" -}}
app.kubernetes.io/name: {{ include "coro.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "coro.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "coro.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: server
{{- end }}

{{- define "coro.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "coro.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "coro.image" -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag -}}
{{- printf "%s:%s-%s" .Values.image.repository $tag .Values.image.flavor }}
{{- end }}

{{- define "coro.modelCacheClaim" -}}
{{- if .Values.modelCache.existingClaim }}
{{- .Values.modelCache.existingClaim }}
{{- else if .Values.modelCache.create }}
{{- printf "%s-model-cache" (include "coro.fullname" .) }}
{{- end }}
{{- end }}

{{- define "coro.validate" -}}
{{- if not (has .Values.autoscaling.mode (list "none" "hpa" "keda")) }}
{{- fail "autoscaling.mode must be none, hpa or keda" }}
{{- end }}
{{- if and .Values.gpu.enabled (ne .Values.image.flavor "gpu") }}
{{- fail "gpu.enabled needs image.flavor=gpu" }}
{{- end }}
{{- if and .Values.modelCache.create .Values.modelCache.existingClaim }}
{{- fail "set modelCache.create or modelCache.existingClaim, not both" }}
{{- end }}
{{- end }}
