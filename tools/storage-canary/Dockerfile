FROM golang:1.26-bookworm@sha256:345775a9b624e690c1c0cd0755149bc8353e221d1c282596564e6d025fd294a9 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags="-s -w" -o /storage-canary .

FROM gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab
COPY --from=build /storage-canary /storage-canary
USER 65532:65532
ENTRYPOINT ["/storage-canary"]
