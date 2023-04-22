{{/*
Expand the name of the chart.
*/}}
{{- define "blocky.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "blocky.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "blocky.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "blocky.labels" -}}
helm.sh/chart: {{ include "blocky.chart" . }}
{{ include "blocky.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "blocky.selectorLabels" -}}
app.kubernetes.io/name: {{ include "blocky.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: {{ include "blocky.name" . }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "blocky.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "blocky.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/* custom */}}

{{- define "blocky.DohTlsTerminatedOnApp" -}}
{{- if and .Values.doh.enabled (eq "app" .Values.doh.tlsTerminationOn) }}
{{- "1" }}
{{- else }}
{{- "" }}
{{- end }}
{{- end }}

{{- define "blocky.DohTlsTerminatedOnIngress" -}}
{{- if and .Values.doh.enabled (eq "ingress" .Values.doh.tlsTerminationOn) }}
{{- "1" }}
{{- else }}
{{- "" }}
{{- end }}
{{- end }}


{{- define "blocky.isCertNeeded" -}}
{{- if and (eq .Values.certificate.type "cert-manager") (or (include "blocky.DohTlsTerminatedOnApp" .) .Values.dot.enabled) }}
    {{- if empty .Values.certificate.spec }}
    {{- fail "Please define spec of certificate under .Values.certificate.spec" }}
    {{- end }}
{{- "1" }}
{{- else }}
{{- "" }}
{{- end }}
{{- end }}


{{- if and .Values.prometheus.enabled (not .Values.http.service.enabled) }}
{{- fail "Can not enable Prometheus without HTTP service. Please set true `http.service.enabled`." }}
{{- end }}
