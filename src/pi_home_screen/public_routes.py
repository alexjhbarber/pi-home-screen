from flask import Flask, Response, jsonify, render_template, send_from_directory

from .runtime import DisplayRuntime


def register_public_routes(app: Flask, runtime: DisplayRuntime) -> None:
    store = runtime.store
    broker = runtime.broker

    @app.get("/")
    def home() -> str:
        return render_template("home.html", settings=store.get())

    @app.get("/api/display")
    def get_display() -> Response:
        settings = store.get().to_dict()
        latest = store.get_latest_result()
        if latest is not None:
            settings["latest_result"] = latest.to_dict()
        return jsonify(settings)

    @app.get("/api/gpio/activity")
    def get_gpio_activity() -> Response:
        paused, activity = store.get_gpio_activity()
        return jsonify(
            paused=paused,
            activity=[
                {
                    "pin": entry.pin,
                    "event": entry.event,
                    "accepted": entry.accepted,
                    "triggered_at": entry.triggered_at,
                }
                for entry in activity
            ],
        )

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename: str) -> Response:
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.get("/events")
    def display_events() -> Response:
        return Response(
            broker.stream(store.get()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
