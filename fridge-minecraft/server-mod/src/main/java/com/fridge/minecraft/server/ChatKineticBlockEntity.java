package com.fridge.minecraft.server;

import net.minecraft.block.BlockState;
import net.minecraft.block.entity.BlockEntity;
import net.minecraft.util.math.BlockPos;

/**
 * Kinetic source driven by stream metrics.
 *
 * Scaling (defaults – tweak to taste):
 *   powerLevel 0  → 0 RPM / 0 SU
 *   powerLevel 15 → MAX_RPM (default 128) / MAX_SU (default 4096)
 *
 * Full Create integration
 * -----------------------
 * To make this a real Create kinetic source you need to:
 *
 * 1. Add Create (Fabric port) as a dependency in build.gradle.
 * 2. Change this class to extend
 *      com.simibubi.create.content.kinetics.base.GeneratingKineticBlockEntity
 * 3. Override:
 *      public float getGeneratedSpeed() {
 *          return rpmForLevel(FridgeServerMod.currentPowerLevel);
 *      }
 * 4. Register stress capacity via Create’s CStress / BlockStressValues
 *    (setCapacity for this block id).
 * 5. Call updateGeneratedRotation() whenever the metrics change
 *    (see the metrics handler in FridgeServerMod).
 *
 * The skeleton below keeps the mod usable without Create while documenting
 * exactly what the finished version looks like.
 */
public class ChatKineticBlockEntity extends BlockEntity {

    public static float MAX_RPM = 128f;
    public static float MAX_SU  = 4096f;

    public ChatKineticBlockEntity(BlockPos pos, BlockState state) {
        super(FridgeServerMod.CHAT_KINETIC_BLOCK_ENTITY, pos, state);
    }

    public static float rpmForLevel(int level) {
        if (level <= 0) return 0f;
        return (MAX_RPM * level) / 15f;
    }

    public static float suForLevel(int level) {
        if (level <= 0) return 0f;
        return (MAX_SU * level) / 15f;
    }

    /** Called every server tick – used for future Create network updates. */
    public void serverTick() {
        // When Create is present you would call:
        //   if (getGeneratedSpeed() != lastSpeed) updateGeneratedRotation();
    }
}
