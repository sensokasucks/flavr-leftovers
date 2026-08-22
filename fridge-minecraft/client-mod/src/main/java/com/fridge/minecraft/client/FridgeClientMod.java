package com.fridge.minecraft.client;

import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpExchange;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.entity.effect.StatusEffectInstance;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.util.Identifier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executors;

/**
 * Client-side Fabric mod.
 * Starts a tiny HTTP server on localhost:3852 that Fridge Stream Core polls.
 * Tracks deaths and can temporarily flag "show inventory".
 */
public class FridgeClientMod implements ClientModInitializer {
    public static final Logger LOGGER = LoggerFactory.getLogger("fridge-minecraft-client");
    public static final int PORT = Integer.getInteger("fridge.client.port", 3852);

    private static int deathCount = 0;
    private static long showInventoryUntil = 0;
    private static boolean wasDead = false;

    @Override
    public void onInitializeClient() {
        LOGGER.info("Fridge Minecraft Client Stats starting on port {}", PORT);
        startHttpServer();

        ClientTickEvents.END_CLIENT_TICK.register(client -> {
            ClientPlayerEntity player = client.player;
            if (player == null) return;

            // simple death detection
            if (player.isDead() || player.getHealth() <= 0) {
                if (!wasDead) {
                    deathCount++;
                    wasDead = true;
                }
            } else {
                wasDead = false;
            }
        });
    }

    private void startHttpServer() {
        try {
            HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", PORT), 0);
            server.createContext("/stats", this::handleStats);
            server.createContext("/health", this::handleHealth);
            server.setExecutor(Executors.newSingleThreadExecutor());
            server.start();
            LOGGER.info("HTTP stats server listening on 127.0.0.1:{}", PORT);
        } catch (IOException e) {
            LOGGER.error("Failed to start HTTP server", e);
        }
    }

    private void handleHealth(HttpExchange ex) throws IOException {
        byte[] body = "ok".getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "text/plain");
        ex.sendResponseHeaders(200, body.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(body);
        }
    }

    private void handleStats(HttpExchange ex) throws IOException {
        MinecraftClient client = MinecraftClient.getInstance();
        ClientPlayerEntity player = client.player;

        StringBuilder json = new StringBuilder();
        json.append("{");
        if (player == null) {
            json.append("\"online\":false");
        } else {
            json.append("\"online\":true,");
            json.append("\"name\":\"").append(escape(player.getName().getString())).append("\",");
            json.append("\"health\":").append(player.getHealth()).append(",");
            json.append("\"maxHealth\":").append(player.getMaxHealth()).append(",");
            json.append("\"food\":").append(player.getHungerManager().getFoodLevel()).append(",");
            json.append("\"saturation\":").append(player.getHungerManager().getSaturationLevel()).append(",");
            json.append("\"xp\":").append(player.experienceLevel).append(",");
            json.append("\"deaths\":").append(deathCount).append(",");
            json.append("\"showInventory\":").append(System.currentTimeMillis() < showInventoryUntil);
            // inventory summary
            json.append(",\"inventory\":[");
            boolean first = true;
            for (int i = 0; i < player.getInventory().size(); i++) {
                ItemStack stack = player.getInventory().getStack(i);
                if (!stack.isEmpty()) {
                    if (!first) json.append(",");
                    first = false;
                    Identifier id = Registries.ITEM.getId(stack.getItem());
                    json.append("{\"slot\":").append(i)
                        .append(",\"id\":\"").append(id).append("\"")
                        .append(",\"count\":").append(stack.getCount()).append("}");
                }
            }
            json.append("]");
        }
        json.append("}");

        byte[] body = json.toString().getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.getResponseHeaders().add("Access-Control-Allow-Origin", "*");
        ex.sendResponseHeaders(200, body.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(body);
        }
    }

    private static String escape(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    /** Called by Stream Core via HTTP when inventory should be shown on overlay. */
    public static void triggerShowInventory(int seconds) {
        showInventoryUntil = System.currentTimeMillis() + seconds * 1000L;
    }
}
