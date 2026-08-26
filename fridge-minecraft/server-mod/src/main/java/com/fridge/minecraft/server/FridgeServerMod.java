package com.fridge.minecraft.server;

import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpExchange;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.object.builder.v1.block.FabricBlockSettings;
import net.fabricmc.fabric.api.object.builder.v1.block.entity.FabricBlockEntityTypeBuilder;
import net.minecraft.block.Block;
import net.minecraft.block.Blocks;
import net.minecraft.block.entity.BlockEntityType;
import net.minecraft.item.BlockItem;
import net.minecraft.item.Item;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.command.ServerCommandSource;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.util.Identifier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import team.reborn.energy.api.EnergyStorage;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;

/**
 * Server-side (or integrated) Fabric mod.
 *
 * - HTTP API for the Stream Core (execute commands + push metrics)
 * - Chat Dynamo  → RF energy (Team Reborn Energy) + redstone fallback
 * - Chat Kinetic → rotational force for Create (see ChatKineticBlockEntity notes)
 */
public class FridgeServerMod implements ModInitializer {
    public static final Logger LOGGER = LoggerFactory.getLogger("fridge-minecraft-server");
    public static final int PORT = Integer.getInteger("fridge.server.port", 3853);

    // ----- blocks -----
    public static final Block CHAT_DYNAMO = new ChatDynamoBlock(
        FabricBlockSettings.copyOf(Blocks.REDSTONE_BLOCK).strength(2.5f)
    );
    public static final Block CHAT_KINETIC = new ChatKineticBlock(
        FabricBlockSettings.copyOf(Blocks.IRON_BLOCK).strength(3.0f)
    );

    // ----- block entities -----
    public static BlockEntityType<ChatDynamoBlockEntity> CHAT_DYNAMO_BLOCK_ENTITY;
    public static BlockEntityType<ChatKineticBlockEntity> CHAT_KINETIC_BLOCK_ENTITY;

    // Shared metrics written by the HTTP handler
    public static volatile int currentPowerLevel = 0;
    public static volatile int viewers = 0;
    public static volatile int cpm = 0;
    public static volatile int commandRate = 0;

    private static MinecraftServer serverInstance;

    @Override
    public void onInitialize() {
        LOGGER.info("Fridge Minecraft Server Interactions starting");

        // Register blocks + items
        Identifier dynamoId = Identifier.of("fridge_minecraft", "chat_dynamo");
        Identifier kineticId = Identifier.of("fridge_minecraft", "chat_kinetic");

        Registry.register(Registries.BLOCK, dynamoId, CHAT_DYNAMO);
        Registry.register(Registries.ITEM, dynamoId, new BlockItem(CHAT_DYNAMO, new Item.Settings()));

        Registry.register(Registries.BLOCK, kineticId, CHAT_KINETIC);
        Registry.register(Registries.ITEM, kineticId, new BlockItem(CHAT_KINETIC, new Item.Settings()));

        // Block entities
        CHAT_DYNAMO_BLOCK_ENTITY = Registry.register(
            Registries.BLOCK_ENTITY_TYPE,
            dynamoId,
            FabricBlockEntityTypeBuilder.create(ChatDynamoBlockEntity::new, CHAT_DYNAMO).build()
        );
        CHAT_KINETIC_BLOCK_ENTITY = Registry.register(
            Registries.BLOCK_ENTITY_TYPE,
            kineticId,
            FabricBlockEntityTypeBuilder.create(ChatKineticBlockEntity::new, CHAT_KINETIC).build()
        );

        // Expose energy storage to the world (TRE sided lookup)
        EnergyStorage.SIDED.registerForBlockEntity(
            (be, direction) -> be.energyStorage,
            CHAT_DYNAMO_BLOCK_ENTITY
        );

        // Capture server instance
        net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents.SERVER_STARTED.register(server -> {
            serverInstance = server;
            startHttpServer();
        });
        net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents.SERVER_STOPPED.register(server -> {
            serverInstance = null;
        });
    }

    private void startHttpServer() {
        try {
            HttpServer http = HttpServer.create(new InetSocketAddress("127.0.0.1", PORT), 0);
            http.createContext("/api/execute", this::handleExecute);
            http.createContext("/api/metrics", this::handleMetrics);
            http.createContext("/api/health", ex -> respond(ex, 200, "{\"ok\":true}"));
            http.setExecutor(Executors.newFixedThreadPool(2));
            http.start();
            LOGGER.info("HTTP API listening on http://127.0.0.1:{}", PORT);
        } catch (IOException e) {
            LOGGER.error("Failed to start HTTP server", e);
        }
    }

    private void handleExecute(HttpExchange ex) throws IOException {
        if (!"POST".equals(ex.getRequestMethod())) {
            ex.sendResponseHeaders(405, -1);
            return;
        }
        String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        String command = extractJsonString(body, "command");
        String playerName = extractJsonString(body, "player");

        if (command == null || command.isBlank()) {
            respond(ex, 400, "{\"success\":false,\"error\":\"missing command\"}");
            return;
        }
        if (serverInstance == null) {
            respond(ex, 503, "{\"success\":false,\"error\":\"server not ready\"}");
            return;
        }

        serverInstance.execute(() -> {
            try {
                ServerCommandSource source = serverInstance.getCommandSource().withLevel(4).withSilent();
                ServerPlayerEntity player = null;
                if (playerName != null) {
                    player = serverInstance.getPlayerManager().getPlayer(playerName);
                }
                if (player != null) {
                    source = player.getCommandSource().withLevel(4).withSilent();
                }
                serverInstance.getCommandManager().executeWithPrefix(source, command);
                LOGGER.info("Executed: {}", command);
            } catch (Exception e) {
                LOGGER.error("Command failed: {}", command, e);
            }
        });

        respond(ex, 200, "{\"success\":true}");
    }

    private void handleMetrics(HttpExchange ex) throws IOException {
        if ("POST".equals(ex.getRequestMethod())) {
            String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            currentPowerLevel = extractJsonInt(body, "powerLevel", currentPowerLevel);
            viewers = extractJsonInt(body, "viewers", viewers);
            cpm = extractJsonInt(body, "cpm", cpm);
            commandRate = extractJsonInt(body, "commands", commandRate);
            // Note: kinetic blocks that have Create integration would call
            // updateGeneratedRotation() here for every placed instance.
            respond(ex, 200, "{\"ok\":true,\"powerLevel\":" + currentPowerLevel + "}");
        } else {
            String json = String.format(
                "{\"viewers\":%d,\"cpm\":%d,\"commands\":%d,\"powerLevel\":%d,\"rfPerTick\":%d}",
                viewers, cpm, commandRate, currentPowerLevel,
                ChatDynamoBlockEntity.rfPerTickForLevel(currentPowerLevel)
            );
            respond(ex, 200, json);
        }
    }

    // ---------- tiny JSON helpers ----------
    private static String extractJsonString(String json, String key) {
        String needle = "\"" + key + "\"";
        int idx = json.indexOf(needle);
        if (idx < 0) return null;
        int colon = json.indexOf(':', idx);
        int startQuote = json.indexOf('"', colon + 1);
        if (startQuote < 0) return null;
        int endQuote = json.indexOf('"', startQuote + 1);
        if (endQuote < 0) return null;
        return json.substring(startQuote + 1, endQuote);
    }

    private static int extractJsonInt(String json, String key, int fallback) {
        String needle = "\"" + key + "\"";
        int idx = json.indexOf(needle);
        if (idx < 0) return fallback;
        int colon = json.indexOf(':', idx);
        int i = colon + 1;
        while (i < json.length() && Character.isWhitespace(json.charAt(i))) i++;
        int j = i;
        while (j < json.length() && (Character.isDigit(json.charAt(j)) || json.charAt(j) == '-')) j++;
        try {
            return Integer.parseInt(json.substring(i, j));
        } catch (Exception e) {
            return fallback;
        }
    }

    private void respond(HttpExchange ex, int code, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.getResponseHeaders().add("Access-Control-Allow-Origin", "*");
        ex.sendResponseHeaders(code, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }
}
