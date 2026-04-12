// tiny_tree.h — pure C++ decision tree inference for ESP8266/ESP32.
//
// Loads a JSON tree from a char buffer, parses it into a compact
// in-memory representation, and provides a walk() function that
// takes a feature vector and returns the predicted class index +
// confidence (leaf sample count).
//
// The JSON format matches what oracle/training.py produces:
//
//   Internal node: {"feature": 3, "threshold": 0.5,
//                   "left": {...}, "right": {...}}
//   Leaf node:     {"value": 1, "samples": 47,
//                   "distribution": [3, 40, 4]}
//
// This file has NO dependency on ArduinoJson. It uses a minimal
// hand-rolled JSON parser that only understands the tree format —
// no arrays-of-arrays, no nested objects beyond the tree structure.
// The parser is ~100 lines and handles the exact shape the Oracle
// serializer produces; nothing more.
//
// Memory budget: each node is 16 bytes (4 fields × 4 bytes).
// A 100-node tree takes 1.6KB RAM. ESP8266 has ~47KB free after
// Velour client + web server + OLED, so ~25 trees fit comfortably.
//
// Usage:
//
//   #include "tiny_tree.h"
//   TinyTree tree;
//   if (tree.loadFromJson(jsonBuffer, jsonLen)) {
//       float features[] = {0.5, 1.0, 3.0, 0.0};
//       int predicted = tree.predict(features);
//       int confidence = tree.leafSamples();
//   }

#ifndef TINY_TREE_H
#define TINY_TREE_H

#include <Arduino.h>

// Maximum number of nodes in a single tree. Each node is 16 bytes,
// so 200 nodes = 3.2KB. Increase if the Oracle produces deeper trees.
#ifndef TINY_TREE_MAX_NODES
#define TINY_TREE_MAX_NODES 200
#endif

// Maximum number of class names
#ifndef TINY_TREE_MAX_CLASSES
#define TINY_TREE_MAX_CLASSES 8
#endif

struct TinyTreeNode {
    int16_t feature;      // feature index (-1 = leaf)
    int16_t value;        // class index (only meaningful if leaf)
    float   threshold;    // split threshold (only meaningful if internal)
    int16_t left;         // index of left child (-1 = none)
    int16_t right;        // index of right child (-1 = none)
    int16_t samples;      // training samples at this node (for confidence)
};


class TinyTree {
public:
    TinyTree() : _nodeCount(0), _classCount(0), _lastLeafIdx(-1) {}

    // Load from a JSON string buffer. Returns true on success.
    // The buffer is NOT retained — the tree is copied into the
    // _nodes array, so the caller can free the buffer after load.
    bool loadFromJson(const char* json, size_t len);

    // Walk the tree with a feature vector. Returns the predicted
    // class index (the "value" field of the reached leaf). Returns
    // -1 if the tree is empty or malformed.
    int predict(const float* features);

    // After predict(), returns the sample count at the reached leaf.
    // Higher = more confident (more training examples reached here).
    int leafSamples() const {
        if (_lastLeafIdx >= 0 && _lastLeafIdx < _nodeCount)
            return _nodes[_lastLeafIdx].samples;
        return 0;
    }

    // Number of nodes loaded.
    int nodeCount() const { return _nodeCount; }

    // Class names (if parsed from the JSON). Index by predict() result.
    const char* className(int idx) const {
        if (idx >= 0 && idx < _classCount)
            return _classNames[idx];
        return "?";
    }
    int classCount() const { return _classCount; }

private:
    TinyTreeNode _nodes[TINY_TREE_MAX_NODES];
    int _nodeCount;
    int _lastLeafIdx;

    char _classNameBuf[TINY_TREE_MAX_CLASSES][24];
    const char* _classNames[TINY_TREE_MAX_CLASSES];
    int _classCount;

    // Minimal JSON helpers — just enough to parse the Oracle format.
    int _parseNode(const char* json, int pos, int len);
    int _skipValue(const char* json, int pos, int len);
    int _skipWhitespace(const char* json, int pos, int len);
    float _parseFloat(const char* json, int& pos, int len);
    int _parseInt(const char* json, int& pos, int len);
    bool _matchKey(const char* json, int pos, int len, const char* key, int& endPos);
};


// =====================================================================
// Implementation (header-only for simplicity on ESP)
// =====================================================================

inline int TinyTree::predict(const float* features) {
    if (_nodeCount == 0) return -1;
    int idx = 0;
    int depth = 0;
    while (idx >= 0 && idx < _nodeCount && depth < 100) {
        const TinyTreeNode& n = _nodes[idx];
        if (n.feature < 0) {
            // Leaf
            _lastLeafIdx = idx;
            return n.value;
        }
        if (features[n.feature] <= n.threshold)
            idx = n.left;
        else
            idx = n.right;
        depth++;
    }
    return -1; // malformed or too deep
}

inline int TinyTree::_skipWhitespace(const char* j, int p, int len) {
    while (p < len && (j[p] == ' ' || j[p] == '\n' || j[p] == '\r' || j[p] == '\t'))
        p++;
    return p;
}

inline float TinyTree::_parseFloat(const char* j, int& p, int len) {
    float val = 0;
    bool neg = false;
    if (p < len && j[p] == '-') { neg = true; p++; }
    while (p < len && j[p] >= '0' && j[p] <= '9') {
        val = val * 10 + (j[p] - '0');
        p++;
    }
    if (p < len && j[p] == '.') {
        p++;
        float frac = 0.1f;
        while (p < len && j[p] >= '0' && j[p] <= '9') {
            val += (j[p] - '0') * frac;
            frac *= 0.1f;
            p++;
        }
    }
    // Skip exponent if present
    if (p < len && (j[p] == 'e' || j[p] == 'E')) {
        p++;
        if (p < len && (j[p] == '+' || j[p] == '-')) p++;
        while (p < len && j[p] >= '0' && j[p] <= '9') p++;
    }
    return neg ? -val : val;
}

inline int TinyTree::_parseInt(const char* j, int& p, int len) {
    int val = 0;
    bool neg = false;
    if (p < len && j[p] == '-') { neg = true; p++; }
    while (p < len && j[p] >= '0' && j[p] <= '9') {
        val = val * 10 + (j[p] - '0');
        p++;
    }
    return neg ? -val : val;
}

inline int TinyTree::_skipValue(const char* j, int p, int len) {
    p = _skipWhitespace(j, p, len);
    if (p >= len) return p;
    if (j[p] == '{') {
        int depth = 1; p++;
        while (p < len && depth > 0) {
            if (j[p] == '{') depth++;
            else if (j[p] == '}') depth--;
            else if (j[p] == '"') {
                p++;
                while (p < len && j[p] != '"') {
                    if (j[p] == '\\') p++;
                    p++;
                }
            }
            p++;
        }
        return p;
    }
    if (j[p] == '[') {
        int depth = 1; p++;
        while (p < len && depth > 0) {
            if (j[p] == '[') depth++;
            else if (j[p] == ']') depth--;
            p++;
        }
        return p;
    }
    if (j[p] == '"') {
        p++;
        while (p < len && j[p] != '"') {
            if (j[p] == '\\') p++;
            p++;
        }
        if (p < len) p++;
        return p;
    }
    // Number, bool, null
    while (p < len && j[p] != ',' && j[p] != '}' && j[p] != ']'
           && j[p] != ' ' && j[p] != '\n' && j[p] != '\r')
        p++;
    return p;
}

inline bool TinyTree::_matchKey(const char* j, int p, int len,
                                 const char* key, int& endPos) {
    p = _skipWhitespace(j, p, len);
    if (p >= len || j[p] != '"') return false;
    p++;
    const char* k = key;
    while (*k && p < len && j[p] == *k) { p++; k++; }
    if (*k != '\0' || p >= len || j[p] != '"') return false;
    p++;
    p = _skipWhitespace(j, p, len);
    if (p >= len || j[p] != ':') return false;
    p++;
    p = _skipWhitespace(j, p, len);
    endPos = p;
    return true;
}

inline int TinyTree::_parseNode(const char* j, int p, int len) {
    if (_nodeCount >= TINY_TREE_MAX_NODES) return -1;
    int myIdx = _nodeCount++;
    TinyTreeNode& n = _nodes[myIdx];
    n.feature = -1; n.value = 0; n.threshold = 0;
    n.left = -1; n.right = -1; n.samples = 0;

    p = _skipWhitespace(j, p, len);
    if (p >= len || j[p] != '{') return -1;
    p++;

    while (p < len && j[p] != '}') {
        p = _skipWhitespace(j, p, len);
        if (p >= len || j[p] == '}') break;

        int valPos;
        if (_matchKey(j, p, len, "feature", valPos)) {
            n.feature = _parseInt(j, valPos, len);
            p = valPos;
        } else if (_matchKey(j, p, len, "threshold", valPos)) {
            n.threshold = _parseFloat(j, valPos, len);
            p = valPos;
        } else if (_matchKey(j, p, len, "value", valPos)) {
            n.value = _parseInt(j, valPos, len);
            p = valPos;
        } else if (_matchKey(j, p, len, "samples", valPos)) {
            n.samples = _parseInt(j, valPos, len);
            p = valPos;
        } else if (_matchKey(j, p, len, "left", valPos)) {
            n.left = _parseNode(j, valPos, len);
            if (n.left < 0) return -1;
            p = _skipValue(j, valPos, len);
            // We already consumed the subtree via _parseNode; need to
            // advance p past the '}' of the subtree we just parsed.
            // _skipValue from valPos will skip the entire subtree.
        } else if (_matchKey(j, p, len, "right", valPos)) {
            n.right = _parseNode(j, valPos, len);
            if (n.right < 0) return -1;
            p = _skipValue(j, valPos, len);
        } else {
            // Unknown key — skip its value
            // Find the end of the key string
            p = _skipWhitespace(j, p, len);
            if (p < len && j[p] == '"') {
                p++;
                while (p < len && j[p] != '"') {
                    if (j[p] == '\\') p++;
                    p++;
                }
                if (p < len) p++;
            }
            p = _skipWhitespace(j, p, len);
            if (p < len && j[p] == ':') p++;
            p = _skipValue(j, p, len);
        }

        p = _skipWhitespace(j, p, len);
        if (p < len && j[p] == ',') p++;
    }
    if (p < len && j[p] == '}') p++;
    return myIdx;
}

inline bool TinyTree::loadFromJson(const char* json, size_t len) {
    _nodeCount = 0;
    _classCount = 0;
    _lastLeafIdx = -1;

    // Find "root": {...} in the top-level object
    int p = 0;
    p = _skipWhitespace(json, p, len);
    if (p >= (int)len || json[p] != '{') return false;
    p++;

    // Walk top-level keys looking for "root" and "classes"
    int rootStart = -1;
    while (p < (int)len && json[p] != '}') {
        p = _skipWhitespace(json, p, (int)len);
        int valPos;
        if (_matchKey(json, p, (int)len, "root", valPos)) {
            int origValPos = valPos;
            rootStart = valPos;
            _parseNode(json, valPos, (int)len);
            p = _skipValue(json, origValPos, (int)len);
        } else if (_matchKey(json, p, (int)len, "classes", valPos)) {
            int origValPos = valPos;
            // Parse the classes array: ["obs", "concern", ...]
            if (valPos < (int)len && json[valPos] == '[') {
                valPos++;
                while (valPos < (int)len && json[valPos] != ']' && _classCount < TINY_TREE_MAX_CLASSES) {
                    valPos = _skipWhitespace(json, valPos, (int)len);
                    if (valPos < (int)len && json[valPos] == '"') {
                        valPos++;
                        int start = valPos;
                        while (valPos < (int)len && json[valPos] != '"') valPos++;
                        int nameLen = valPos - start;
                        if (nameLen > 23) nameLen = 23;
                        memcpy(_classNameBuf[_classCount], json + start, nameLen);
                        _classNameBuf[_classCount][nameLen] = '\0';
                        _classNames[_classCount] = _classNameBuf[_classCount];
                        _classCount++;
                        if (valPos < (int)len) valPos++;
                    }
                    valPos = _skipWhitespace(json, valPos, (int)len);
                    if (valPos < (int)len && json[valPos] == ',') valPos++;
                }
            }
            // Always skip from the ORIGINAL position so we don't
            // double-advance past the next key.
            p = _skipValue(json, origValPos, (int)len);
        } else {
            // Skip unknown top-level key
            p = _skipWhitespace(json, p, (int)len);
            if (p < (int)len && json[p] == '"') {
                p++;
                while (p < (int)len && json[p] != '"') {
                    if (json[p] == '\\') p++;
                    p++;
                }
                if (p < (int)len) p++;
            }
            p = _skipWhitespace(json, p, (int)len);
            if (p < (int)len && json[p] == ':') p++;
            p = _skipValue(json, p, (int)len);
        }
        p = _skipWhitespace(json, p, (int)len);
        if (p < (int)len && json[p] == ',') p++;
    }

    return _nodeCount > 0;
}

#endif // TINY_TREE_H
