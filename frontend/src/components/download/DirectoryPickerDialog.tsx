import {
  Button,
  Flex,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Text,
} from "@chakra-ui/react";
import { getParentPath } from "../../lib/util";

interface DirectoryPickerDialogProps {
  isOpen: boolean;
  onClose: () => void;
  loading: boolean;
  path: string;
  entries: string[];
  onNavigate: (path: string) => void;
  onSelect: (path: string) => void;
}

/**
 * Server-side directory picker. Chakra ``Modal`` handles focus trap /
 * ESC-to-close; the body is a plain list of directories returned by
 * ``/api/directories``.
 */
export function DirectoryPickerDialog({
  isOpen,
  onClose,
  loading,
  path,
  entries,
  onNavigate,
  onSelect,
}: DirectoryPickerDialogProps) {
  const parent = getParentPath(path);
  return (
    <Modal isOpen={isOpen} onClose={onClose} size="xl" isCentered>
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>Choose download directory</ModalHeader>
        <ModalCloseButton />
        <ModalBody>
          <Flex align="center" justify="space-between" mb={3}>
            <Text fontFamily="mono" fontSize="sm" noOfLines={1}>
              {path || "/"}
            </Text>
            {parent && (
              <Button size="sm" variant="ghost" onClick={() => onNavigate(parent)}>
                Up ↑
              </Button>
            )}
          </Flex>
          {loading ? (
            <Flex justify="center" py={6}>
              <Spinner />
            </Flex>
          ) : entries.length === 0 ? (
            <Text fontSize="sm" color="gray.500">
              No sub-directories under this path.
            </Text>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {entries.map((entry) => (
                <li key={entry}>
                  <button
                    type="button"
                    onClick={() => onNavigate(entry)}
                    style={{
                      display: "block",
                      width: "100%",
                      textAlign: "left",
                      padding: "8px 12px",
                      fontFamily: "var(--font-mono)",
                      fontSize: 13,
                      background: "transparent",
                      border: "1px solid transparent",
                      borderRadius: "var(--radius-sm)",
                      color: "var(--ink)",
                      cursor: "pointer",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background =
                        "color-mix(in oklch, var(--accent-500) 10%, transparent)";
                      e.currentTarget.style.borderColor = "var(--surface-border)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = "transparent";
                      e.currentTarget.style.borderColor = "transparent";
                    }}
                  >
                    {entry}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" mr={3} onClick={onClose}>
            Cancel
          </Button>
          <Button colorScheme="blue" onClick={() => onSelect(path)}>
            Use this directory
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
