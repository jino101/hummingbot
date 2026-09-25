package com.jino.arbitrage;

import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.ViewGroup;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.net.URI;

public class MainActivity extends Activity {
    private static final String PREFS = "jino";
    private static final String KEY_URL = "dashboard_url";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String url = prefs.getString(KEY_URL, "");
        if (isAllowedUrl(url)) {
            showDashboard(url);
        } else {
            showSetup();
        }
    }

    private boolean isAllowedUrl(String value) {
        if (value == null || value.isBlank()) return false;
        try {
            URI uri = URI.create(value.trim());
            return "https".equalsIgnoreCase(uri.getScheme()) && uri.getHost() != null;
        } catch (Exception ignored) {
            return false;
        }
    }

    private void showSetup() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(48, 80, 48, 48);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setBackgroundColor(Color.rgb(7, 11, 20));

        TextView title = new TextView(this);
        title.setText("JINO");
        title.setTextColor(Color.WHITE);
        title.setTextSize(34);
        title.setGravity(Gravity.CENTER);

        TextView info = new TextView(this);
        info.setText("Verbinde die App mit deinem Jino-Dashboard.\nNur HTTPS-Adressen werden akzeptiert.\nDie App kann Trading nicht freischalten.");
        info.setTextColor(Color.rgb(160, 172, 194));
        info.setTextSize(16);
        info.setPadding(0, 28, 0, 28);

        EditText input = new EditText(this);
        input.setHint("https://dein-jino-server.example");
        input.setSingleLine(true);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setTextColor(Color.WHITE);
        input.setHintTextColor(Color.rgb(110, 125, 150));

        Button connect = new Button(this);
        connect.setText("VERBINDEN");
        connect.setOnClickListener(v -> {
            String url = input.getText().toString().trim();
            if (!isAllowedUrl(url)) {
                input.setError("Bitte eine gültige HTTPS-Adresse eingeben.");
                return;
            }
            getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_URL, url).apply();
            showDashboard(url);
        });

        root.addView(title, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(info, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(input, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(connect, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        setContentView(root);
    }

    private void showDashboard(String url) {
        WebView web = new WebView(this);
        web.setBackgroundColor(Color.rgb(7, 11, 20));
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.setWebViewClient(new WebViewClient());
        web.loadUrl(url);
        setContentView(web);
    }
}
