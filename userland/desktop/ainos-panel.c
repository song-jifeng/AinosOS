// 文件名: desktop/ainos-panel.c
#include <gtk/gtk.h>
#include <glib.h>
#include <time.h>
#include <stdio.h>

#define PANEL_HEIGHT 36
#define ICON_SIZE 24

/* 更新时钟 */
static gboolean update_clock(gpointer user_data) {
    GtkLabel *clock_label = GTK_LABEL(user_data);
    time_t rawtime;
    struct tm * timeinfo;
    char buffer[80];

    time (&rawtime);
    timeinfo = localtime (&rawtime);
    strftime (buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", timeinfo);

    gtk_label_set_text(clock_label, buffer);
    return G_SOURCE_CONTINUE;
}

/* 启动器按钮点击事件 */
static void on_app_launcher_clicked(GtkButton *button, gpointer user_data) {
    g_print("Ainos App Launcher clicked. Opening application menu...\n");
    // 这里可以调用 Ainos SDK 或 DBus 打开应用菜单
}

/* 系统设置按钮点击事件 */
static void on_settings_clicked(GtkButton *button, gpointer user_data) {
    g_print("Opening Ainos Control Panel...\n");
    // 启动 control_panel.py
    g_spawn_command_line_async("python3 /opt/ainos/userland/control-panel/control_panel.py", NULL);
}

static void activate(GtkApplication *app, gpointer user_data) {
    GtkWidget *window;
    GtkWidget *box;
    GtkWidget *launcher_btn;
    GtkWidget *settings_btn;
    GtkWidget *clock_label;
    GtkWidget *spacer;

    window = gtk_application_window_new(app);
    gtk_window_set_title(GTK_WINDOW(window), "Ainos Panel");
    gtk_window_set_default_size(GTK_WINDOW(window), 1920, PANEL_HEIGHT);
    
    // 设置为置顶和固定窗口 (Wayland/X11 兼容的 Dock 属性)
    gtk_window_set_type_hint(GTK_WINDOW(window), GDK_WINDOW_TYPE_HINT_DOCK);
    gtk_window_set_decorated(GTK_WINDOW(window), FALSE);
    gtk_window_stick(GTK_WINDOW(window));
    gtk_window_set_skip_taskbar_hint(GTK_WINDOW(window), TRUE);
    gtk_window_set_skip_pager_hint(GTK_WINDOW(window), TRUE);

    // 主水平布局
    box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 5);
    gtk_container_add(GTK_CONTAINER(window), box);
    gtk_widget_set_margin_start(box, 10);
    gtk_widget_set_margin_end(box, 10);

    // 1. AI 启动器按钮
    launcher_btn = gtk_button_new_with_label("🚀 Ainos AI");
    g_signal_connect(launcher_btn, "clicked", G_CALLBACK(on_app_launcher_clicked), NULL);
    gtk_box_pack_start(GTK_BOX(box), launcher_btn, FALSE, FALSE, 0);

    // 2. 弹性空白区域
    spacer = gtk_label_new("");
    gtk_box_pack_start(GTK_BOX(box), spacer, TRUE, TRUE, 0);

    // 3. 系统状态/设置
    settings_btn = gtk_button_new_with_label("⚙️ Settings");
    g_signal_connect(settings_btn, "clicked", G_CALLBACK(on_settings_clicked), NULL);
    gtk_box_pack_end(GTK_BOX(box), settings_btn, FALSE, FALSE, 0);

    // 4. 时钟
    clock_label = gtk_label_new("0000-00-00 00:00:00");
    gtk_box_pack_end(GTK_BOX(box), clock_label, FALSE, FALSE, 5);
    
    // 每秒更新时钟
    g_timeout_add_seconds(1, update_clock, clock_label);
    update_clock(clock_label); // 立即更新一次

    gtk_widget_show_all(window);
}

int main(int argc, char **argv) {
    GtkApplication *app;
    int status;

    app = gtk_application_new("os.ainos.panel", G_APPLICATION_FLAGS_NONE);
    g_signal_connect(app, "activate", G_CALLBACK(activate), NULL);
    status = g_application_run(G_APPLICATION(app), argc, argv);
    g_object_unref(app);

    return status;
}
