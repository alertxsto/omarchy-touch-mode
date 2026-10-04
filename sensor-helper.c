/*
 * SensorProxy uses the system bus: net.hadess.SensorProxy,
 * /net/hadess/SensorProxy, interface net.hadess.SensorProxy.
 * HasAccelerometer is boolean; AccelerometerOrientation is a string:
 * normal, bottom-up, left-up, right-up, or undefined (not yet determined).
 * ClaimAccelerometer/ReleaseAccelerometer take no arguments; claims belong
 * to the calling bus connection. PropertiesChanged drives updates, not polls.
 * Stdout is newline-delimited JSON; diagnostics go only to stderr.
 */
#include <gio/gio.h>
#include <glib-unix.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define SENSOR_NAME "net.hadess.SensorProxy"
#define SENSOR_PATH "/net/hadess/SensorProxy"
#define METHOD_TIMEOUT_MS 5000

typedef struct {
    GDBusProxy *proxy;
    GMainLoop *loop;
    gchar *owner;
    gboolean claimed;
    gboolean stopping;
    int status;
} Client;

typedef struct {
    gboolean available;
    GVariant *orientation_value;
    const gchar *orientation;
} Snapshot;

static void fail(Client *client, const gchar *message)
{
    if (!client->stopping)
        g_printerr("Sensor backend: %s\n", message);
    client->status = 1;
    client->stopping = TRUE;
    if (client->loop != NULL)
        g_main_loop_quit(client->loop);
}

static gboolean snapshot_read(Client *client, Snapshot *snapshot)
{
    GVariant *available = g_dbus_proxy_get_cached_property(client->proxy,
                                                         "HasAccelerometer");
    if (available == NULL || !g_variant_is_of_type(available, G_VARIANT_TYPE_BOOLEAN)) {
        g_clear_pointer(&available, g_variant_unref);
        fail(client, "SensorProxy has no valid HasAccelerometer property.");
        return FALSE;
    }
    snapshot->available = g_variant_get_boolean(available);
    g_variant_unref(available);
    snapshot->orientation_value = g_dbus_proxy_get_cached_property(
        client->proxy, "AccelerometerOrientation");
    if (snapshot->orientation_value == NULL ||
        !g_variant_is_of_type(snapshot->orientation_value, G_VARIANT_TYPE_STRING)) {
        g_clear_pointer(&snapshot->orientation_value, g_variant_unref);
        fail(client, "SensorProxy has no valid AccelerometerOrientation property.");
        return FALSE;
    }
    snapshot->orientation = g_variant_get_string(snapshot->orientation_value, NULL);
    const gchar *orientation = snapshot->orientation;
    if (!g_str_equal(orientation, "normal") &&
        !g_str_equal(orientation, "bottom-up") &&
        !g_str_equal(orientation, "left-up") &&
        !g_str_equal(orientation, "right-up") &&
        !g_str_equal(orientation, "undefined")) {
        g_variant_unref(snapshot->orientation_value);
        fail(client, "SensorProxy returned an unsupported accelerometer orientation.");
        return FALSE;
    }
    return TRUE;
}

static gboolean emit_snapshot(Client *client, const Snapshot *snapshot,
                              gboolean sensor_event)
{
    int result;
    /* Orientation has been whitelisted, so it needs no JSON escaping. */
    if (sensor_event)
        result = printf("{\"event\":\"sensor\",\"available\":%s,\"orientation\":\"%s\"}\n",
                        snapshot->available ? "true" : "false", snapshot->orientation);
    else
        result = printf("{\"event\":\"orientation\",\"orientation\":\"%s\"}\n",
                        snapshot->orientation);
    if (result < 0 || fflush(stdout) == EOF) {
        fail(client, "Cannot write sensor events to stdout.");
        return FALSE;
    }
    return TRUE;
}

static gboolean method_call(Client *client, const gchar *method)
{
    GError *error = NULL;
    GVariant *reply = g_dbus_proxy_call_sync(client->proxy, method, NULL,
                                           G_DBUS_CALL_FLAGS_NO_AUTO_START,
                                           METHOD_TIMEOUT_MS, NULL, &error);
    if (reply == NULL) {
        g_printerr("Sensor backend: %s failed: %s\n", method, error->message);
        g_error_free(error);
        client->status = 1;
        return FALSE;
    }
    gboolean valid = g_variant_is_of_type(reply, G_VARIANT_TYPE_UNIT);
    g_variant_unref(reply);
    if (!valid) {
        g_printerr("Sensor backend: %s returned a malformed reply.\n", method);
        client->status = 1;
    }
    return valid;
}

static void properties_changed(GDBusProxy *proxy, GVariant *changed,
                               const gchar *const *invalidated, gpointer data)
{
    (void) proxy;
    Client *client = data;
    if (client->stopping)
        return;
    GVariant *has = g_variant_lookup_value(changed, "HasAccelerometer", NULL);
    GVariant *orientation = g_variant_lookup_value(changed, "AccelerometerOrientation", NULL);
    gboolean has_changed = has != NULL;
    gboolean orientation_changed = orientation != NULL;
    g_clear_pointer(&has, g_variant_unref);
    g_clear_pointer(&orientation, g_variant_unref);
    for (guint i = 0; invalidated != NULL && invalidated[i] != NULL; ++i) {
        has_changed |= g_str_equal(invalidated[i], "HasAccelerometer");
        orientation_changed |= g_str_equal(invalidated[i], "AccelerometerOrientation");
    }
    if (!has_changed && !orientation_changed)
        return;
    Snapshot snapshot = {0};
    if (!snapshot_read(client, &snapshot))
        return;
    emit_snapshot(client, &snapshot, has_changed);
    if (!snapshot.available)
        fail(client, "The accelerometer is no longer available.");
    g_variant_unref(snapshot.orientation_value);
}

static void owner_changed(GObject *object, GParamSpec *spec, gpointer data)
{
    (void) object;
    (void) spec;
    Client *client = data;
    gchar *owner = g_dbus_proxy_get_name_owner(client->proxy);
    if (g_strcmp0(owner, client->owner) != 0)
        fail(client, "The SensorProxy service disappeared or was replaced.");
    g_free(owner);
}

static void connection_closed(GDBusConnection *connection, gboolean remote_peer_vanished,
                              GError *error, gpointer data)
{
    (void) connection;
    (void) remote_peer_vanished;
    (void) error;
    fail(data, "The system D-Bus connection closed.");
}

static gboolean stop_signal(gpointer data)
{
    Client *client = data;
    client->stopping = TRUE;
    g_main_loop_quit(client->loop);
    return G_SOURCE_CONTINUE;
}

static gboolean stdin_ready(gint fd, GIOCondition condition, gpointer data)
{
    Client *client = data;
    if (condition & (G_IO_HUP | G_IO_ERR | G_IO_NVAL))
        return stop_signal(client);
    char buffer[256];
    ssize_t count = read(fd, buffer, sizeof buffer);
    if (count == 0)
        return stop_signal(client);
    if (count < 0 && errno != EINTR && errno != EAGAIN) {
        fail(client, "Cannot read the parent stdin pipe.");
    }
    return G_SOURCE_CONTINUE;
}

int main(int argc, char **argv)
{
    if (argc != 2 || (strcmp(argv[1], "--probe") != 0 &&
                      strcmp(argv[1], "--watch") != 0)) {
        g_printerr("Usage: sensor-helper --probe | --watch\n");
        return 2;
    }
    gboolean watch = strcmp(argv[1], "--watch") == 0;
    /* Broken consumer pipes must still allow ReleaseAccelerometer cleanup. */
    signal(SIGPIPE, SIG_IGN);
    Client client = {0};
    GError *error = NULL;
    client.proxy = g_dbus_proxy_new_for_bus_sync(
        G_BUS_TYPE_SYSTEM, G_DBUS_PROXY_FLAGS_GET_INVALIDATED_PROPERTIES,
        NULL, SENSOR_NAME, SENSOR_PATH, SENSOR_NAME, NULL, &error);
    if (client.proxy == NULL) {
        g_printerr("Sensor backend: Cannot connect to SensorProxy: %s\n", error->message);
        g_error_free(error);
        return 1;
    }
    client.owner = g_dbus_proxy_get_name_owner(client.proxy);
    if (client.owner == NULL) {
        fail(&client, "SensorProxy is not running. Install and start iio-sensor-proxy.");
        goto cleanup;
    }
    Snapshot initial = {0};
    if (!snapshot_read(&client, &initial))
        goto cleanup;
    if (!watch || !initial.available) {
        emit_snapshot(&client, &initial, TRUE);
        if (!initial.available)
            fail(&client, "SensorProxy reports that no accelerometer is available.");
        g_variant_unref(initial.orientation_value);
        goto cleanup;
    }
    g_variant_unref(initial.orientation_value);
    if (!method_call(&client, "ClaimAccelerometer"))
        goto cleanup;
    client.claimed = TRUE;
    client.loop = g_main_loop_new(NULL, FALSE);
    GDBusConnection *connection = g_dbus_proxy_get_connection(client.proxy);
    g_dbus_connection_set_exit_on_close(connection, FALSE);
    gulong property_handler = g_signal_connect(client.proxy, "g-properties-changed",
                                               G_CALLBACK(properties_changed), &client);
    gulong owner_handler = g_signal_connect(client.proxy, "notify::g-name-owner",
                                            G_CALLBACK(owner_changed), &client);
    gulong closed_handler = g_signal_connect(connection, "closed",
                                             G_CALLBACK(connection_closed), &client);
    guint term_source = g_unix_signal_add(SIGTERM, stop_signal, &client);
    guint int_source = g_unix_signal_add(SIGINT, stop_signal, &client);
    guint stdin_source = 0;
    struct stat input;
    /* Quickshell retains a stdin pipe; interactive terminals and /dev/null
     * must not be interpreted as a parent lifetime channel. */
    if (fstat(STDIN_FILENO, &input) == 0 &&
        (S_ISFIFO(input.st_mode) || S_ISSOCK(input.st_mode)))
        stdin_source = g_unix_fd_add(STDIN_FILENO, G_IO_IN | G_IO_HUP | G_IO_ERR | G_IO_NVAL,
                                    stdin_ready, &client);
    Snapshot claimed = {0};
    if (snapshot_read(&client, &claimed)) {
        emit_snapshot(&client, &claimed, TRUE);
        if (!claimed.available)
            fail(&client, "The accelerometer became unavailable while claiming it.");
        g_variant_unref(claimed.orientation_value);
    }
    if (!client.stopping)
        g_main_loop_run(client.loop);
    if (stdin_source != 0)
        g_source_remove(stdin_source);
    g_source_remove(term_source);
    g_source_remove(int_source);
    g_signal_handler_disconnect(client.proxy, property_handler);
    g_signal_handler_disconnect(client.proxy, owner_handler);
    g_signal_handler_disconnect(connection, closed_handler);

cleanup:
    if (client.claimed) {
        gchar *owner = g_dbus_proxy_get_name_owner(client.proxy);
        /* A vanished service has already discarded this connection's claim.
         * Never release into a replacement service with a different owner. */
        if (g_strcmp0(owner, client.owner) == 0 &&
            !g_dbus_connection_is_closed(g_dbus_proxy_get_connection(client.proxy)))
            method_call(&client, "ReleaseAccelerometer");
        g_free(owner);
    }
    g_clear_pointer(&client.loop, g_main_loop_unref);
    g_free(client.owner);
    g_object_unref(client.proxy);
    return client.status;
}
