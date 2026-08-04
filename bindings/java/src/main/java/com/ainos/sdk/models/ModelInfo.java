package com.ainos.sdk.models;

import java.util.Objects;

/**
 * Metadata describing a single registered model managed by the Ainos daemon.
 * <p>
 * This class is immutable and thread-safe.
 */
public final class ModelInfo {

    private final String id;
    private final String name;
    private final String path;
    private final long sizeMb;
    private final boolean loaded;
    private final String architecture;

    /**
     * Constructs a new ModelInfo instance.
     *
     * @param id           unique model identifier
     * @param name         human-readable model name
     * @param path         absolute file path on disk
     * @param sizeMb       model file size in megabytes
     * @param loaded       whether the model is currently loaded in memory
     * @param architecture model architecture string (e.g. {@code "auto"}, {@code "phi3"})
     */
    public ModelInfo(String id, String name, String path, long sizeMb, boolean loaded, String architecture) {
        this.id = Objects.requireNonNull(id, "id must not be null");
        this.name = Objects.requireNonNull(name, "name must not be null");
        this.path = Objects.requireNonNull(path, "path must not be null");
        this.sizeMb = sizeMb;
        this.loaded = loaded;
        this.architecture = Objects.requireNonNull(architecture, "architecture must not be null");
    }

    /** Returns the unique model identifier. */
    public String getId() {
        return id;
    }

    /** Returns the human-readable model name. */
    public String getName() {
        return name;
    }

    /** Returns the absolute file path on disk. */
    public String getPath() {
        return path;
    }

    /** Returns the model file size in megabytes. */
    public long getSizeMb() {
        return sizeMb;
    }

    /** Returns whether the model is currently loaded in memory. */
    public boolean isLoaded() {
        return loaded;
    }

    /** Returns the model architecture string. */
    public String getArchitecture() {
        return architecture;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ModelInfo)) return false;
        ModelInfo modelInfo = (ModelInfo) o;
        return sizeMb == modelInfo.sizeMb
                && loaded == modelInfo.loaded
                && id.equals(modelInfo.id)
                && name.equals(modelInfo.name)
                && path.equals(modelInfo.path)
                && architecture.equals(modelInfo.architecture);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, name, path, sizeMb, loaded, architecture);
    }

    @Override
    public String toString() {
        return "ModelInfo{"
                + "id='" + id + '\''
                + ", name='" + name + '\''
                + ", loaded=" + loaded
                + ", architecture='" + architecture + '\''
                + '}';
    }
}