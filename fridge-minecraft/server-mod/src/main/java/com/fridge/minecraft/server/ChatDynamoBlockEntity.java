package com.fridge.minecraft.server;

import net.fabricmc.fabric.api.transfer.v1.transaction.Transaction;
import net.minecraft.block.BlockState;
import net.minecraft.block.entity.BlockEntity;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Direction;
import team.reborn.energy.api.EnergyStorage;
import team.reborn.energy.api.EnergyStorageUtil;
import team.reborn.energy.api.base.SimpleEnergyStorage;

/**
 * Block entity that generates and pushes TRE energy.
 *
 * Scaling:
 *   powerLevel 0  → 0 RF/t
 *   powerLevel 15 → MAX_RF_PER_TICK (default 2400)
 *
 * Energy is push-based (TRE convention): every tick we generate into the
 * internal buffer, then try to move energy into adjacent storages.
 *
 * Energy 4.x uses Fabric Transaction API — insert/extract take a
 * TransactionContext, not a simulate boolean.
 */
public class ChatDynamoBlockEntity extends BlockEntity {

    /** Max RF generated per tick when powerLevel == 15. */
    public static long MAX_RF_PER_TICK = 2400L;

    /** Internal buffer so short spikes of demand can be smoothed. */
    public static final long CAPACITY = 50_000L;

    /**
     * maxInsert = CAPACITY so generation can fill the buffer.
     * maxExtract = Long.MAX_VALUE so we can push freely to neighbors.
     */
    public final SimpleEnergyStorage energyStorage = new SimpleEnergyStorage(
            CAPACITY, CAPACITY, Long.MAX_VALUE
    ) {
        @Override
        protected void onFinalCommit() {
            markDirty();
        }
    };

    public ChatDynamoBlockEntity(BlockPos pos, BlockState state) {
        super(FridgeServerMod.CHAT_DYNAMO_BLOCK_ENTITY, pos, state);
    }

    public static long rfPerTickForLevel(int level) {
        if (level <= 0) return 0;
        return (MAX_RF_PER_TICK * level) / 15;
    }

    public void tick() {
        if (world == null || world.isClient) return;

        long generate = rfPerTickForLevel(FridgeServerMod.currentPowerLevel);
        if (generate > 0) {
            try (Transaction tx = Transaction.openOuter()) {
                energyStorage.insert(generate, tx);
                tx.commit();
            }
        }

        // Push to adjacent energy storages (TRE is push-based)
        for (Direction dir : Direction.values()) {
            if (energyStorage.amount <= 0) break;

            EnergyStorage target = EnergyStorage.SIDED.find(world, pos.offset(dir), dir.getOpposite());
            if (target == null || !target.supportsInsertion()) continue;

            EnergyStorageUtil.move(energyStorage, target, energyStorage.amount, null);
        }
    }
}
